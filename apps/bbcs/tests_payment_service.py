"""
tests_payment_service.py — Testes da service de confirmação de pagamentos.

Cobertura:
  - Criação de Payment, LedgerEntries e OutboxEvent em transação atômica
  - Retorno de created=True no primeiro chamado, created=False na repetição
  - Idempotência: mesma chave + mesmo payload não duplica registros
  - Conflito: mesma chave + payload diferente levanta PaymentConflictError
  - Valores financeiros calculados corretamente (PIX e CARD 3x)
  - LedgerEntries criadas com valores e percentuais corretos
  - OutboxEvent criado com type=payment_captured e status=pending
  - Payload do OutboxEvent contém todos os campos necessários
  - Normalização do hash: ordenação de chaves não afeta o resultado
"""

from decimal import Decimal

import pytest

from apps.audit.models import OutboxEvent
from apps.bbcs.models import LedgerEntry, Payment
from apps.bbcs.services.payment_service import PaymentConflictError, confirm_payment


@pytest.mark.django_db
class TestConfirmPaymentCreation:

    def test_returns_payment_outbox_and_created_true(self, service_pix_data, idempotency_key):
        """Primeira chamada deve retornar (Payment, OutboxEvent, True)."""
        payment, outbox_event, created = confirm_payment(service_pix_data, idempotency_key)

        assert isinstance(payment, Payment)
        assert isinstance(outbox_event, OutboxEvent)
        assert created is True

    def test_payment_persisted_in_db(self, service_pix_data, idempotency_key):
        """Payment deve estar persistido no banco após a chamada."""
        confirm_payment(service_pix_data, idempotency_key)

        assert Payment.objects.filter(idempotency_key=idempotency_key).exists()

    def test_ledger_entries_created(self, service_pix_data, idempotency_key):
        """LedgerEntries devem ser criadas para cada participante do split."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        entries = LedgerEntry.objects.filter(payment=payment)
        assert entries.count() == 2

    def test_outbox_event_persisted(self, service_pix_data, idempotency_key):
        """OutboxEvent deve estar persistido com type=payment_captured e status=pending."""
        payment, outbox_event, _ = confirm_payment(service_pix_data, idempotency_key)

        assert outbox_event.type == "payment_captured"
        assert outbox_event.status == "pending"
        assert OutboxEvent.objects.filter(id=outbox_event.id).exists()

    def test_outbox_payload_contains_payment_id(self, service_pix_data, idempotency_key):
        """Payload do OutboxEvent deve conter o payment_id do pagamento criado."""
        payment, outbox_event, _ = confirm_payment(service_pix_data, idempotency_key)

        assert outbox_event.payload["payment_id"] == str(payment.id)

    def test_outbox_payload_contains_all_fields(self, service_pix_data, idempotency_key):
        """Payload do OutboxEvent deve conter gross, fee, net, method, installments, currency, status."""
        _, outbox_event, _ = confirm_payment(service_pix_data, idempotency_key)

        required_keys = {
            "payment_id", "gross_amount", "platform_fee_amount",
            "net_amount", "payment_method", "installments", "currency", "status",
        }
        assert required_keys.issubset(outbox_event.payload.keys())


@pytest.mark.django_db
class TestConfirmPaymentFinancials:

    def test_pix_zero_fee(self, service_pix_data, idempotency_key):
        """PIX: platform_fee_amount deve ser zero e net_amount igual ao gross."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert payment.platform_fee_amount == Decimal("0.00")
        assert payment.net_amount == Decimal("100.00")
        assert payment.gross_amount == Decimal("100.00")

    def test_card_3x_fee_and_net(self, service_card_data, idempotency_key):
        """CARD 3x: fee = floor(297 × 8,99%) = 26.70, net = 270.30."""
        payment, _, _ = confirm_payment(service_card_data, idempotency_key)

        assert payment.platform_fee_amount == Decimal("26.70")
        assert payment.net_amount == Decimal("270.30")

    def test_ledger_entries_sum_equals_net_amount(self, service_card_data, idempotency_key):
        """Soma dos LedgerEntries deve ser igual ao net_amount do pagamento."""
        payment, _, _ = confirm_payment(service_card_data, idempotency_key)

        total = sum(e.amount for e in payment.ledger_entries.all())
        assert total == payment.net_amount

    def test_ledger_entry_percent_stored_correctly(self, service_pix_data, idempotency_key):
        """Percentuais dos LedgerEntries devem refletir os splits informados."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        entries = {e.recipient_id: e for e in payment.ledger_entries.all()}
        assert entries["producer_1"].percent == Decimal("70.00")
        assert entries["affiliate_9"].percent == Decimal("30.00")

    def test_payment_status_is_captured(self, service_pix_data, idempotency_key):
        """Status do pagamento deve ser 'captured' após confirmação."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert payment.status == "captured"

    def test_payment_currency_stored(self, service_pix_data, idempotency_key):
        """Moeda deve ser persistida como 'BRL'."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert payment.currency == "BRL"

    def test_idempotency_key_stored(self, service_pix_data, idempotency_key):
        """idempotency_key deve ser persistida no registro do pagamento."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert payment.idempotency_key == idempotency_key

    def test_payload_hash_stored(self, service_pix_data, idempotency_key):
        """idempotency_payload_hash deve ser preenchido com 64 caracteres (SHA-256)."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert len(payment.idempotency_payload_hash) == 64


@pytest.mark.django_db
class TestConfirmPaymentIdempotency:

    def test_repeat_call_returns_created_false(self, service_pix_data, idempotency_key):
        """Segunda chamada com mesma chave e mesmo payload deve retornar created=False."""
        confirm_payment(service_pix_data, idempotency_key)
        _, _, created = confirm_payment(service_pix_data, idempotency_key)

        assert created is False

    def test_repeat_call_does_not_duplicate_payment(self, service_pix_data, idempotency_key):
        """Duas chamadas com a mesma chave devem resultar em um único Payment no banco."""
        confirm_payment(service_pix_data, idempotency_key)
        confirm_payment(service_pix_data, idempotency_key)

        assert Payment.objects.filter(idempotency_key=idempotency_key).count() == 1

    def test_repeat_call_does_not_duplicate_ledger_entries(self, service_pix_data, idempotency_key):
        """Repetição idempotente não deve criar novos LedgerEntries."""
        payment, _, _ = confirm_payment(service_pix_data, idempotency_key)
        confirm_payment(service_pix_data, idempotency_key)

        assert LedgerEntry.objects.filter(payment=payment).count() == 2

    def test_repeat_call_returns_same_payment(self, service_pix_data, idempotency_key):
        """Chamada idempotente deve retornar o mesmo objeto Payment da primeira chamada."""
        payment_first, _, _ = confirm_payment(service_pix_data, idempotency_key)
        payment_second, _, _ = confirm_payment(service_pix_data, idempotency_key)

        assert payment_first.id == payment_second.id

    def test_repeat_call_returns_associated_outbox_event(self, service_pix_data, idempotency_key):
        """Chamada idempotente deve retornar o OutboxEvent associado ao pagamento original."""
        _, outbox_first, _ = confirm_payment(service_pix_data, idempotency_key)
        _, outbox_second, _ = confirm_payment(service_pix_data, idempotency_key)

        assert outbox_first.id == outbox_second.id

    def test_hash_order_independent(self, idempotency_key):
        """Payloads com chaves em ordens diferentes devem gerar o mesmo hash."""
        data_a = {
            "amount": Decimal("50.00"),
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [{"recipient_id": "r1", "role": "Industria", "percent": Decimal("100.00")}],
        }
        data_b = {
            "installments": 1,
            "splits": [{"recipient_id": "r1", "role": "Industria", "percent": Decimal("100.00")}],
            "payment_method": "pix",
            "currency": "BRL",
            "amount": Decimal("50.00"),
        }

        payment_a, _, _ = confirm_payment(data_a, idempotency_key)
        _, _, created = confirm_payment(data_b, idempotency_key + "-b")

        # Ambos criaram pagamentos independentes — apenas verificamos que a_hash == b_hash
        # indiretamente: se data_b fosse enviado com a mesma chave de data_a,
        # seria tratado como idempotente (não conflito).
        from apps.bbcs.services.payment_service import _compute_payload_hash
        assert _compute_payload_hash(data_a) == _compute_payload_hash(data_b)


@pytest.mark.django_db
class TestConfirmPaymentConflict:

    def test_different_payload_raises_conflict_error(self, service_pix_data, idempotency_key):
        """Mesma chave com payload diferente deve levantar PaymentConflictError."""
        confirm_payment(service_pix_data, idempotency_key)

        different_data = {**service_pix_data, "amount": Decimal("200.00")}
        with pytest.raises(PaymentConflictError):
            confirm_payment(different_data, idempotency_key)

    def test_conflict_error_message(self, service_pix_data, idempotency_key):
        """Mensagem do PaymentConflictError deve orientar o cliente a usar nova chave."""
        confirm_payment(service_pix_data, idempotency_key)

        different_data = {**service_pix_data, "amount": Decimal("999.00")}
        with pytest.raises(PaymentConflictError, match="nova chave"):
            confirm_payment(different_data, idempotency_key)

    def test_conflict_does_not_create_new_payment(self, service_pix_data, idempotency_key):
        """Conflito não deve criar um segundo Payment no banco."""
        confirm_payment(service_pix_data, idempotency_key)
        different_data = {**service_pix_data, "amount": Decimal("500.00")}

        with pytest.raises(PaymentConflictError):
            confirm_payment(different_data, idempotency_key)

        assert Payment.objects.filter(idempotency_key=idempotency_key).count() == 1

    def test_different_keys_create_independent_payments(self, service_pix_data):
        """Chaves diferentes com payloads diferentes devem criar pagamentos independentes."""
        _, _, created_1 = confirm_payment(service_pix_data, "key-001")
        different_data = {**service_pix_data, "amount": Decimal("200.00")}
        _, _, created_2 = confirm_payment(different_data, "key-002")

        assert created_1 is True
        assert created_2 is True
        assert Payment.objects.count() == 2
