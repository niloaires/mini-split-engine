"""
payment_service.py — Serviço de confirmação de pagamentos.

Responsabilidades:
  - Verificar idempotência: mesma chave + mesmo payload → retorna resultado existente.
  - Detectar conflito: mesma chave + payload diferente → levanta PaymentConflictError.
  - Executar a transação atômica: Payment + LedgerEntries + OutboxEvent em um único commit.

Por que a atomicidade fica aqui e não na view?
  A view é responsável apenas pelo protocolo HTTP (entrada, saída, status codes).
  A garantia de consistência — "ou tudo persiste, ou nada persiste" — é uma regra
  de negócio, e portanto pertence à camada de serviço.

Estratégia de idempotência:
  1. Normaliza o payload com json.dumps(sort_keys=True) antes de calcular o hash.
     Garante que a ordenação das chaves não produza hashes diferentes para o mesmo payload.
  2. Busca Payment pela idempotency_key.
  3. Se encontrado: compara o hash armazenado com o hash atual.
     - Hashes iguais   → retorna (payment, outbox_event, created=False).
     - Hashes diferentes → levanta PaymentConflictError.
  4. Se não encontrado: calcula, persiste e retorna (payment, outbox_event, created=True).
"""

import hashlib
import json

from django.db import transaction

from apps.audit.models import OutboxEvent, OutboxEventTypeEnum
from apps.bbcs.models import LedgerEntry, Payment, PaymentStatusEnum
from apps.bbcs.services.split_calculator import SplitInput, calculate_payment
from apps.core.handlers import LoggerEngine

logger = LoggerEngine(origin="payment_service")


class PaymentConflictError(Exception):
    """
    Levantada quando a mesma Idempotency-Key é reutilizada com um payload diferente.

    O cliente não deve retentar com a mesma chave — deve gerar uma nova chave
    para um pagamento diferente.
    """


def _to_json_serializable(data):
    """
    Converte um dict com valores Decimal em um dict serializável pelo JSONField do Django.

    validated_data do DRF contém Decimal — o JSONField padrão não os serializa.
    A conversão via json.dumps/loads com default=str garante que todos os tipos
    não-nativos sejam representados como strings antes da persistência.
    """
    return json.loads(json.dumps(data, default=str))


def _compute_payload_hash(payload: dict) -> str:
    """
    Calcula o SHA-256 do payload normalizado.

    A normalização via sort_keys=True garante que dicionários com a mesma
    estrutura mas chaves em ordens diferentes produzam o mesmo hash.
    """
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _build_outbox_payload(payment: Payment) -> dict:
    """
    Constrói o payload do OutboxEvent a partir do pagamento confirmado.

    Inclui todos os dados necessários para que o consumidor processe o evento
    sem precisar consultar o banco novamente.
    """
    return {
        "payment_id": str(payment.id),
        "gross_amount": str(payment.gross_amount),
        "platform_fee_amount": str(payment.platform_fee_amount),
        "net_amount": str(payment.net_amount),
        "payment_method": payment.payment_method,
        "installments": payment.installments,
        "currency": payment.currency,
        "status": payment.status,
    }


def confirm_payment(
    validated_data: dict,
    idempotency_key: str,
) -> tuple[Payment, OutboxEvent, bool]:
    """
    Confirma um pagamento de forma idempotente e atômica.

    Fluxo:
        1. Normaliza o payload e calcula o hash SHA-256.
        2. Busca Payment existente pela idempotency_key.
           - Encontrado, hash igual      → retorna resultado existente (created=False).
           - Encontrado, hash diferente  → levanta PaymentConflictError.
           - Não encontrado              → executa a transação atômica.
        3. Na transação atômica:
           a. Calcula gross_amount, fee, net_amount e split via calculate_payment.
           b. Cria Payment com status=captured.
           c. Cria LedgerEntry para cada recebedor via bulk_create.
           d. Cria OutboxEvent com type=payment_captured e status=pending.

    Args:
        validated_data: Dados já validados pelo PaymentInputSerializer.
        idempotency_key: Chave fornecida pelo cliente via header Idempotency-Key.

    Returns:
        Tupla (Payment, OutboxEvent, created).
        created=True indica novo pagamento; False indica retorno idempotente.

    Raises:
        PaymentConflictError: Mesma chave com payload diferente.
    """
    payload_hash = _compute_payload_hash(validated_data)
    logger.registrar(
        f"Iniciando confirm_payment | idempotency_key={idempotency_key} "
        f"| method={validated_data.get('payment_method')} "
        f"| amount={validated_data.get('amount')}",
        level="INFO",
    )

    existing = Payment.allobjects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.idempotency_payload_hash == payload_hash:
            logger.registrar(
                f"Retorno idempotente | payment_id={existing.id} | idempotency_key={idempotency_key}",
                level="INFO",
            )
            outbox_event = OutboxEvent.allobjects.filter(
                payload__payment_id=str(existing.id)
            ).first()
            return existing, outbox_event, False
        logger.registrar(
            f"Conflito de idempotência | idempotency_key={idempotency_key}",
            level="WARNING",
        )
        raise PaymentConflictError(
            "A Idempotency-Key já foi utilizada com um payload diferente. "
            "Use uma nova chave para um pagamento diferente."
        )

    splits = [
        SplitInput(
            recipient_id=s["recipient_id"],
            role=s["role"],
            percent=s["percent"],
        )
        for s in validated_data["splits"]
    ]

    result = calculate_payment(
        gross_amount=validated_data["amount"],
        payment_method=validated_data["payment_method"],
        installments=validated_data["installments"],
        splits=splits,
    )
    logger.registrar(
        f"Cálculo concluído | gross={result.gross_amount} "
        f"| fee={result.platform_fee_amount} | net={result.net_amount} "
        f"| recebedores={len(result.receivables)}",
        level="DEBUG",
    )

    with transaction.atomic():
        payment = Payment.objects.create(
            gross_amount=result.gross_amount,
            platform_fee_amount=result.platform_fee_amount,
            net_amount=result.net_amount,
            payment_method=validated_data["payment_method"],
            installments=validated_data["installments"],
            currency=validated_data["currency"],
            status=PaymentStatusEnum.CAPTURED.code,
            idempotency_key=idempotency_key,
            idempotency_payload_hash=payload_hash,
            payload=_to_json_serializable(validated_data),
        )
        logger.registrar(
            f"Payment criado | payment_id={payment.id} | status={payment.status}",
            level="INFO",
        )

        LedgerEntry.objects.bulk_create([
            LedgerEntry(
                payment=payment,
                recipient_id=r.recipient_id,
                role=r.role,
                percent=r.percent,
                amount=r.amount,
            )
            for r in result.receivables
        ])
        logger.registrar(
            f"LedgerEntries criadas | payment_id={payment.id} | count={len(result.receivables)}",
            level="DEBUG",
        )

        outbox_event = OutboxEvent.objects.create(
            type=OutboxEventTypeEnum.PAYMENT_CAPTURED.code,
            payload=_build_outbox_payload(payment),
        )
        logger.registrar(
            f"OutboxEvent criado | payment_id={payment.id} | type={outbox_event.type} | status={outbox_event.status}",
            level="INFO",
        )

    return payment, outbox_event, True
