"""
tests_views.py — Testes dos endpoints de pagamento via APIClient.

Cobertura:
  POST /api/v1/payments (PaymentViewSet.create):
    - 201 Created: pagamento novo criado com sucesso
    - 200 OK: retorno idempotente (mesma chave, mesmo payload)
    - 400 Bad Request: payload inválido (campos ausentes, regras de negócio)
    - 409 Conflict: mesma chave com payload diferente
    - 422 Unprocessable: header Idempotency-Key ausente

  POST /api/v1/checkout/quote (PaymentViewSet.quote):
    - 200 OK: cálculo realizado sem persistir
    - 400 Bad Request: payload inválido

  Estrutura da resposta:
    - campos obrigatórios presentes (payment_id, status, gross_amount, etc.)
    - receivables com recipient_id, role e amount
    - outbox_event com type e status
"""

import pytest
from rest_framework import status

PAYMENTS_URL = "/api/v1/payments/"
QUOTE_URL = "/api/v1/checkout/payments/quote/"


@pytest.mark.django_db
class TestCreatePayment:

    def test_201_creates_payment(self, api_client, pix_payload, idempotency_key):
        """Payload válido com header Idempotency-Key deve retornar 201."""
        response = api_client.post(
            PAYMENTS_URL,
            data=pix_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_201_response_structure(self, api_client, pix_payload, idempotency_key):
        """Resposta 201 deve conter todos os campos do contrato da API."""
        response = api_client.post(
            PAYMENTS_URL,
            data=pix_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        data = response.json()

        required_fields = {
            "payment_id", "status", "gross_amount",
            "platform_fee_amount", "net_amount", "receivables", "outbox_event",
        }
        assert required_fields.issubset(data.keys())

    def test_201_receivables_structure(self, api_client, pix_payload, idempotency_key):
        """Cada recebível deve ter recipient_id, role e amount."""
        response = api_client.post(
            PAYMENTS_URL,
            data=pix_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        receivables = response.json()["receivables"]

        assert len(receivables) == 2
        for r in receivables:
            assert "recipient_id" in r
            assert "role" in r
            assert "amount" in r

    def test_201_outbox_event_structure(self, api_client, pix_payload, idempotency_key):
        """outbox_event deve ter type=payment_captured e status=pending."""
        response = api_client.post(
            PAYMENTS_URL,
            data=pix_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        outbox = response.json()["outbox_event"]

        assert outbox["type"] == "payment_captured"
        assert outbox["status"] == "pending"

    def test_201_pix_zero_fee(self, api_client, pix_payload, idempotency_key):
        """PIX deve retornar platform_fee_amount=0.00 e net_amount=gross_amount."""
        response = api_client.post(
            PAYMENTS_URL,
            data=pix_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        data = response.json()

        assert data["platform_fee_amount"] == "0.00"
        assert data["net_amount"] == data["gross_amount"]

    def test_201_card_3x_fee_and_net(self, api_client, card_3x_payload, idempotency_key):
        """CARD 3x: fee=26.70, net=270.30."""
        response = api_client.post(
            PAYMENTS_URL,
            data=card_3x_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        data = response.json()

        assert data["platform_fee_amount"] == "26.70"
        assert data["net_amount"] == "270.30"

    def test_200_idempotent_repeat(self, api_client, pix_payload, idempotency_key):
        """Segunda chamada com mesma chave e payload deve retornar 200 OK."""
        api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                        HTTP_IDEMPOTENCY_KEY=idempotency_key)
        response = api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_200_OK

    def test_200_idempotent_same_payment_id(self, api_client, pix_payload, idempotency_key):
        """Retorno idempotente deve ter o mesmo payment_id da resposta original."""
        r1 = api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                             HTTP_IDEMPOTENCY_KEY=idempotency_key)
        r2 = api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                             HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert r1.json()["payment_id"] == r2.json()["payment_id"]

    def test_409_conflict_different_payload(self, api_client, pix_payload, idempotency_key):
        """Mesma chave com payload diferente deve retornar 409 Conflict."""
        api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                        HTTP_IDEMPOTENCY_KEY=idempotency_key)

        different_payload = {**pix_payload, "amount": "200.00"}
        response = api_client.post(PAYMENTS_URL, data=different_payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_409_response_has_detail(self, api_client, pix_payload, idempotency_key):
        """Resposta 409 deve conter campo 'detail' com mensagem explicativa."""
        api_client.post(PAYMENTS_URL, data=pix_payload, format="json",
                        HTTP_IDEMPOTENCY_KEY=idempotency_key)
        different_payload = {**pix_payload, "amount": "999.00"}
        response = api_client.post(PAYMENTS_URL, data=different_payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert "detail" in response.json()

    def test_422_missing_idempotency_key_header(self, api_client, pix_payload):
        """Ausência do header Idempotency-Key deve retornar 422."""
        response = api_client.post(PAYMENTS_URL, data=pix_payload, format="json")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_422_response_has_detail(self, api_client, pix_payload):
        """Resposta 422 deve informar que o header é obrigatório."""
        response = api_client.post(PAYMENTS_URL, data=pix_payload, format="json")

        assert "detail" in response.json()

    def test_400_missing_required_field(self, api_client, idempotency_key):
        """Payload sem campo obrigatório deve retornar 400."""
        incomplete = {"currency": "BRL", "payment_method": "pix", "installments": 1}
        response = api_client.post(PAYMENTS_URL, data=incomplete, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_pix_with_installments(self, api_client, idempotency_key):
        """PIX com installments > 1 deve retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 3,
            "splits": [
                {"recipient_id": "r1", "role": "Industria", "percent": "100.00"}
            ],
        }
        response = api_client.post(PAYMENTS_URL, data=payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_split_percent_not_100(self, api_client, idempotency_key):
        """Splits cuja soma dos percentuais ≠ 100 devem retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [
                {"recipient_id": "r1", "role": "Industria", "percent": "70.00"},
                {"recipient_id": "r2", "role": "distributor", "percent": "20.00"},
            ],
        }
        response = api_client.post(PAYMENTS_URL, data=payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_more_than_5_splits(self, api_client, idempotency_key):
        """Mais de 5 participantes no split deve retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [
                {"recipient_id": f"r{i}", "role": "Industria", "percent": "16.00"}
                for i in range(6)
            ],
        }
        response = api_client.post(PAYMENTS_URL, data=payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_invalid_currency(self, api_client, idempotency_key):
        """Moeda diferente de BRL deve retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "USD",
            "payment_method": "pix",
            "installments": 1,
            "splits": [{"recipient_id": "r1", "role": "Industria", "percent": "100.00"}],
        }
        response = api_client.post(PAYMENTS_URL, data=payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_amount_zero(self, api_client, idempotency_key):
        """amount=0 deve retornar 400 (min_value=0.01)."""
        payload = {
            "amount": "0.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [{"recipient_id": "r1", "role": "Industria", "percent": "100.00"}],
        }
        response = api_client.post(PAYMENTS_URL, data=payload, format="json",
                                   HTTP_IDEMPOTENCY_KEY=idempotency_key)

        assert response.status_code == status.HTTP_400_BAD_REQUEST



@pytest.mark.django_db
class TestQuotePayment:

    def test_200_returns_quote(self, api_client, pix_payload):
        """Payload válido deve retornar 200 com o cálculo."""
        response = api_client.post(QUOTE_URL, data=pix_payload, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_200_response_structure(self, api_client, pix_payload):
        """Resposta deve conter gross_amount, platform_fee_amount, net_amount e receivables."""
        response = api_client.post(QUOTE_URL, data=pix_payload, format="json")
        data = response.json()

        assert "gross_amount" in data
        assert "platform_fee_amount" in data
        assert "net_amount" in data
        assert "receivables" in data

    def test_200_no_payment_id_in_quote(self, api_client, pix_payload):
        """Quote não deve expor payment_id — nenhum dado é persistido."""
        response = api_client.post(QUOTE_URL, data=pix_payload, format="json")
        data = response.json()

        assert "payment_id" not in data
        assert "outbox_event" not in data

    def test_200_pix_zero_fee(self, api_client, pix_payload):
        """PIX: platform_fee_amount deve ser 0.00."""
        response = api_client.post(QUOTE_URL, data=pix_payload, format="json")
        data = response.json()

        assert data["platform_fee_amount"] == "0.00"
        assert data["gross_amount"] == data["net_amount"]

    def test_200_card_3x_fee(self, api_client, card_3x_payload):
        """CARD 3x: fee=26.70, net=270.30."""
        response = api_client.post(QUOTE_URL, data=card_3x_payload, format="json")
        data = response.json()

        assert data["platform_fee_amount"] == "26.70"
        assert data["net_amount"] == "270.30"

    def test_200_receivables_count(self, api_client, pix_payload):
        """Número de recebíveis deve corresponder ao número de splits enviados."""
        response = api_client.post(QUOTE_URL, data=pix_payload, format="json")
        data = response.json()

        assert len(data["receivables"]) == len(pix_payload["splits"])

    def test_200_does_not_persist_payment(self, api_client, pix_payload):
        """Quote não deve criar registros no banco de dados."""
        from apps.bbcs.models import Payment
        api_client.post(QUOTE_URL, data=pix_payload, format="json")

        assert Payment.objects.count() == 0

    def test_400_split_sum_not_100(self, api_client):
        """Splits com soma ≠ 100 devem retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [
                {"recipient_id": "r1", "role": "Industria", "percent": "50.00"},
            ],
        }
        response = api_client.post(QUOTE_URL, data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_more_than_5_splits(self, api_client):
        """Mais de 5 participantes no split deve retornar 400."""
        payload = {
            "amount": "100.00",
            "currency": "BRL",
            "payment_method": "pix",
            "installments": 1,
            "splits": [
                {"recipient_id": f"r{i}", "role": "Industria", "percent": "16.00"}
                for i in range(6)
            ],
        }
        response = api_client.post(QUOTE_URL, data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
