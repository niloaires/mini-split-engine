"""
views.py — Views do domínio de pagamentos.

Padrão adotado: GenericViewSet + mixins do DRF.

Por que GenericViewSet + mixins?
  - Granularidade: só os mixins necessários são incluídos, deixando explícito
    quais operações cada ViewSet suporta.
  - Integração com Router: o DefaultRouter do DRF gera as URLs automaticamente
    a partir das actions declaradas, eliminando boilerplate em urls.py.
  - Separação de responsabilidades: a view cuida apenas de HTTP (entrada,
    saída, status codes); toda lógica de negócio e persistência fica na service.

Atomicidade:
  A transação atômica (Payment + LedgerEntries + OutboxEvent em um único
  commit) é responsabilidade da service de pagamento, não da view. A view
  apenas chama a service e trata os resultados.
"""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import mixins, serializers, status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.bbcs.serializers import (
    PaymentInputSerializer,
    PaymentOutputSerializer,
    QuoteOutputSerializer,
)
from apps.bbcs.services.payment_service import PaymentConflictError, confirm_payment
from apps.bbcs.services.split_calculator import SplitInput, calculate_payment

_ErrorSerializer = inline_serializer(
    name="ErrorDetail",
    fields={"detail": serializers.CharField()},
)

_IDEMPOTENCY_KEY_PARAM = OpenApiParameter(
    name="Idempotency-Key",
    location=OpenApiParameter.HEADER,
    required=True,
    type=str,
    description=(
        "Chave única gerada pelo cliente para garantir idempotência. "
        "Requisições repetidas com a mesma chave e o mesmo payload retornam o resultado "
        "original sem criar um novo pagamento. "
        "Usar a mesma chave com um payload diferente resulta em 409 Conflict."
    ),
    examples=[
        OpenApiExample(
            name="UUID v4",
            value="550e8400-e29b-41d4-a716-446655440000",
        )
    ],
)


class PaymentViewSet(mixins.CreateModelMixin, GenericViewSet):
    """
    ViewSet para operações de pagamento.

    Endpoints:
        POST /api/v1/payments           — confirma e persiste um pagamento.
        POST /api/v1/checkout/quote     — simula o cálculo sem persistir.

    O mixin CreateModelMixin fornece o método `create` para o endpoint principal.
    O endpoint de simulação é declarado como @action extra para manter o mesmo
    ViewSet como ponto de entrada do domínio de pagamentos.
    """

    serializer_class = PaymentInputSerializer

    @extend_schema(
        tags=["Pagamentos"],
        summary="Confirmar pagamento",
        description=(
            "Processa e persiste um pagamento de forma atômica: cria o `Payment`, "
            "os `LedgerEntry` de cada recebedor e o `OutboxEvent` em uma única transação.\n\n"
            "**Idempotência:** envie o header `Idempotency-Key` em toda requisição. "
            "Requisições repetidas com a mesma chave e o mesmo payload retornam `200 OK` "
            "com o resultado original, sem duplicar o pagamento. "
            "A mesma chave com payload diferente retorna `409 Conflict`.\n\n"
            "**Taxas aplicadas (fallback padrão):**\n"
            "- PIX: 0%\n"
            "- Cartão 1×: 3,99%\n"
            "- Cartão 2–12×: 4,99% + 2% por parcela adicional\n\n"
            "Quando um `Plan` com `is_default=True` estiver cadastrado, "
            "as taxas são lidas da `fee_table` do plano."
        ),
        request=PaymentInputSerializer,
        parameters=[_IDEMPOTENCY_KEY_PARAM],
        responses={
            201: OpenApiResponse(
                response=PaymentOutputSerializer,
                description="Pagamento criado com sucesso.",
                examples=[
                    OpenApiExample(
                        name="PIX — 2 recebedores",
                        value={
                            "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                            "status": "captured",
                            "gross_amount": "1000.00",
                            "platform_fee_amount": "0.00",
                            "net_amount": "1000.00",
                            "receivables": [
                                {"recipient_id": "producer_1", "role": "Industria", "amount": "700.00"},
                                {"recipient_id": "affiliate_9", "role": "distributor", "amount": "300.00"},
                            ],
                            "outbox_event": {"type": "payment_captured", "status": "pending"},
                        },
                    )
                ],
            ),
            200: OpenApiResponse(
                response=PaymentOutputSerializer,
                description=(
                    "Retorno idempotente — mesma `Idempotency-Key` com mesmo payload. "
                    "Nenhum novo registro foi criado."
                ),
            ),
            400: OpenApiResponse(
                response=_ErrorSerializer,
                description="Payload inválido. Verifique os campos e tente novamente.",
                examples=[
                    OpenApiExample(
                        name="Soma dos percentuais inválida",
                        value={"splits": ["A soma dos percentuais deve ser 100. Recebido: 90."]},
                    ),
                    OpenApiExample(
                        name="PIX com parcelamento",
                        value={"installments": ["PIX não aceita parcelamento. Use installments=1."]},
                    ),
                ],
            ),
            409: OpenApiResponse(
                response=_ErrorSerializer,
                description=(
                    "Conflito de idempotência — a `Idempotency-Key` já foi utilizada "
                    "com um payload diferente. Gere uma nova chave."
                ),
                examples=[
                    OpenApiExample(
                        name="Conflito",
                        value={
                            "detail": (
                                "A Idempotency-Key já foi utilizada com um payload diferente. "
                                "Use uma nova chave para um pagamento diferente."
                            )
                        },
                    )
                ],
            ),
            422: OpenApiResponse(
                response=_ErrorSerializer,
                description="Header `Idempotency-Key` ausente na requisição.",
                examples=[
                    OpenApiExample(
                        name="Header ausente",
                        value={"detail": "O header Idempotency-Key é obrigatório."},
                    )
                ],
            ),
        },
    )
    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/payments

        Confirma um pagamento. Requer o header Idempotency-Key.

        Fluxo:
            1. Valida o payload via PaymentInputSerializer.
            2. Extrai a Idempotency-Key do header.
            3. Delega para confirm_payment (service), que executa em transação atômica:
               Payment + LedgerEntries + OutboxEvent.
            4. Serializa e retorna a resposta via PaymentOutputSerializer.

        Status codes:
            201 Created         — pagamento criado com sucesso.
            200 OK              — mesma Idempotency-Key com mesmo payload (idempotente).
            409 Conflict        — mesma Idempotency-Key com payload diferente.
            400 Bad Request     — payload inválido.
            422 Unprocessable   — Idempotency-Key ausente no header.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"detail": "O header Idempotency-Key é obrigatório."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            payment, outbox_event, created = confirm_payment(
                validated_data=serializer.validated_data,
                idempotency_key=idempotency_key,
            )
        except PaymentConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        payment.outbox_event = outbox_event
        output = PaymentOutputSerializer(payment)
        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(output.data, status=http_status)

    @extend_schema(
        tags=["Pagamentos"],
        summary="Simular cálculo de split (quote)",
        description=(
            "Calcula taxas e distribui o valor líquido entre os recebedores "
            "**sem persistir nenhum dado**. "
            "Use este endpoint para exibir o resumo financeiro ao usuário "
            "antes de confirmar o pagamento.\n\n"
            "O cálculo segue as mesmas regras do endpoint de confirmação: "
            "taxa sobre o `gross_amount`, `net_amount = gross_amount − taxa`, "
            "e split do `net_amount` proporcional aos percentuais informados. "
            "Centavos residuais são absorvidos pelo primeiro recebedor da lista."
        ),
        request=PaymentInputSerializer,
        responses={
            200: OpenApiResponse(
                response=QuoteOutputSerializer,
                description="Cálculo realizado com sucesso.",
                examples=[
                    OpenApiExample(
                        name="Cartão 2× — 3 recebedores",
                        value={
                            "gross_amount": "500.00",
                            "platform_fee_amount": "44.95",
                            "net_amount": "455.05",
                            "receivables": [
                                {"recipient_id": "producer_1", "role": "Industria", "amount": "318.53"},
                                {"recipient_id": "affiliate_9", "role": "distributor", "amount": "91.01"},
                                {"recipient_id": "co_1", "role": "coproducer", "amount": "45.51"},
                            ],
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                response=_ErrorSerializer,
                description="Payload inválido.",
                examples=[
                    OpenApiExample(
                        name="Mais de 5 participantes",
                        value={"splits": ["O split deve ter entre 1 e 5 participantes."]},
                    )
                ],
            ),
        },
    )
    def quote(self, request):
        """
        POST /api/v1/checkout/quote

        Simula o cálculo de taxas e split sem persistir nenhum dado.
        Útil para exibir o resumo financeiro antes da confirmação do pagamento.

        Status codes:
            200 OK          — cálculo realizado com sucesso.
            400 Bad Request — payload inválido.
        """
        serializer = PaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        splits = [
            SplitInput(
                recipient_id=s["recipient_id"],
                role=s["role"],
                percent=s["percent"],
            )
            for s in data["splits"]
        ]

        result = calculate_payment(
            gross_amount=data["amount"],
            payment_method=data["payment_method"],
            installments=data["installments"],
            splits=splits,
        )

        output = QuoteOutputSerializer({
            "gross_amount": result.gross_amount,
            "platform_fee_amount": result.platform_fee_amount,
            "net_amount": result.net_amount,
            "receivables": [
                {"recipient_id": r.recipient_id, "role": r.role, "amount": r.amount}
                for r in result.receivables
            ],
        })

        return Response(output.data, status=status.HTTP_200_OK)
