"""
serializers.py — Serializers de entrada e saída para o endpoint de pagamentos.

Estratégia de uso de ModelSerializer:
  - Serializers de saída usam ModelSerializer onde há correspondência direta com
    um model (LedgerEntry, OutboxEvent, Payment), aproveitando as definições de
    campo já declaradas no model e evitando duplicação.
  - Serializers de entrada usam Serializer simples porque o payload de entrada
    não mapeia diretamente para um único model — ele orquestra a criação de
    Payment + LedgerEntry(s) + OutboxEvent em uma única operação.
  - SplitInputSerializer usa ModelSerializer sobre LedgerEntry para reaproveitar
    as definições de recipient_id, role e percent, adicionando apenas as
    validações de negócio que o model não expressa (min_value do percent).

Responsabilidades:
  - SplitInputSerializer: valida cada participante do split (aninhado).
  - PaymentInputSerializer: valida o payload de entrada do POST /api/v1/payments.
  - ReceivableOutputSerializer: serializa cada LedgerEntry na resposta.
  - OutboxEventOutputSerializer: serializa o OutboxEvent na resposta.
  - PaymentOutputSerializer: serializa a resposta completa do pagamento confirmado.
  - QuoteOutputSerializer: serializa a resposta do endpoint de simulação (sem payment_id).
"""

from decimal import Decimal

from rest_framework import serializers

from apps.audit.models import OutboxEvent
from apps.bbcs.models import LedgerEntry, Payment, PaymentMethodEnum


class SplitInputSerializer(serializers.ModelSerializer):
    """
    Valida um participante do split reaproveitando a definição de LedgerEntry.

    Usa ModelSerializer para herdar as definições de campo de LedgerEntry
    (max_length, max_digits, decimal_places), evitando duplicação. O campo
    percent recebe um validador adicional de min_value=0.01, que não é
    exprimível como constraint de banco mas é uma regra de negócio obrigatória.

    Campos expostos: recipient_id, role, percent.
    Os demais campos de LedgerEntry (payment, amount, created_at etc.) são
    preenchidos pela service após o cálculo — não fazem parte da entrada.
    """

    percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("100"),
    )

    class Meta:
        model = LedgerEntry
        fields = ["recipient_id", "role", "percent"]


class PaymentInputSerializer(serializers.Serializer):
    """
    Valida o payload de entrada do endpoint POST /api/v1/payments.

    Usa Serializer simples porque o payload orquestra a criação de múltiplos
    models (Payment, LedgerEntry, OutboxEvent) e não mapeia para um único model.

    Regras de negócio aplicadas:
        - amount: maior que zero, até 2 casas decimais.
        - currency: apenas "BRL".
        - payment_method: "pix" ou "card".
        - installments: 1–12 para card; PIX não aceita parcelamento (deve ser 1).
        - splits: entre 1 e 5 participantes; soma dos percentuais deve ser 100.
    """

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    currency = serializers.ChoiceField(choices=["BRL"])
    payment_method = serializers.ChoiceField(
        choices=[m.code for m in PaymentMethodEnum]
    )
    installments = serializers.IntegerField(min_value=1, max_value=12, default=1)
    splits = SplitInputSerializer(many=True)

    def validate_splits(self, splits):
        """Garante entre 1 e 5 participantes e soma dos percentuais igual a 100."""
        if not 1 <= len(splits) <= 5:
            raise serializers.ValidationError(
                "O split deve ter entre 1 e 5 participantes."
            )

        total_percent = sum(s["percent"] for s in splits)
        if total_percent != Decimal("100"):
            raise serializers.ValidationError(
                f"A soma dos percentuais deve ser 100. Recebido: {total_percent}."
            )

        return splits

    def validate(self, data):
        """Valida regras cruzadas entre payment_method e installments."""
        method = data.get("payment_method")
        installments = data.get("installments", 1)

        if method == "pix" and installments != 1:
            raise serializers.ValidationError(
                {"installments": "PIX não aceita parcelamento. Use installments=1."}
            )

        return data



class ReceivableOutputSerializer(serializers.ModelSerializer):
    """
    Serializa um LedgerEntry como recebível na resposta.

    ModelSerializer garante que os tipos e precisões dos campos (DecimalField
    com max_digits e decimal_places) sejam herdados diretamente do model,
    sem necessidade de redeclaração.
    """

    class Meta:
        model = LedgerEntry
        fields = ["recipient_id", "role", "amount"]


class OutboxEventOutputSerializer(serializers.ModelSerializer):
    """
    Serializa um OutboxEvent na resposta.

    Expõe apenas type e status — os demais campos (payload, published_at,
    created_at) são internos ao sistema e não devem ser expostos na API.
    """

    class Meta:
        model = OutboxEvent
        fields = ["type", "status"]


class PaymentOutputSerializer(serializers.ModelSerializer):
    """
    Serializa a resposta completa do endpoint POST /api/v1/payments.

    ModelSerializer sobre Payment, com campos aninhados para os recebíveis
    (LedgerEntry via related_name='ledger_entries') e para o outbox_event
    (passado via contexto pela view, pois não há FK de Payment para OutboxEvent).

    O campo payment_id usa source='id' para renomear o UUID na resposta,
    mantendo o contrato da API sem expor o nome interno do campo.
    """

    payment_id = serializers.UUIDField(source="id", read_only=True)
    receivables = ReceivableOutputSerializer(many=True, source="ledger_entries")
    outbox_event = OutboxEventOutputSerializer(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "payment_id",
            "status",
            "gross_amount",
            "platform_fee_amount",
            "net_amount",
            "receivables",
            "outbox_event",
        ]


class QuoteOutputSerializer(serializers.Serializer):
    """
    Serializa a resposta do endpoint POST /api/v1/checkout/quote.

    Usa Serializer simples porque a simulação não persiste objetos — não há
    instâncias de model para o ModelSerializer introspeccionar. Os campos
    espelham os valores calculados pelo split_calculator diretamente.
    """

    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    platform_fee_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    receivables = ReceivableOutputSerializer(many=True)
