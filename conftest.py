"""
conftest.py — Fixtures compartilhadas entre todos os testes.

Disponibiliza dados base reutilizáveis para os testes de views e services,
evitando duplicação de setup entre os módulos de teste.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    """Cliente HTTP sem autenticação para testes de endpoints públicos."""
    return APIClient()


@pytest.fixture
def pix_payload():
    """Payload válido de pagamento PIX com 2 recebedores (70/30)."""
    return {
        "amount": "100.00",
        "currency": "BRL",
        "payment_method": "pix",
        "installments": 1,
        "splits": [
            {"recipient_id": "producer_1", "role": "Industria", "percent": "70.00"},
            {"recipient_id": "affiliate_9", "role": "distributor", "percent": "30.00"},
        ],
    }


@pytest.fixture
def card_3x_payload():
    """Payload válido de pagamento CARD 3x com 2 recebedores (70/30)."""
    return {
        "amount": "297.00",
        "currency": "BRL",
        "payment_method": "card",
        "installments": 3,
        "splits": [
            {"recipient_id": "producer_1", "role": "Industria", "percent": "70.00"},
            {"recipient_id": "affiliate_9", "role": "distributor", "percent": "30.00"},
        ],
    }


@pytest.fixture
def idempotency_key():
    """Chave de idempotência padrão para testes."""
    return "test-idempotency-key-001"


@pytest.fixture
def service_pix_data():
    """validated_data equivalente para uso direto na service (valores Decimal)."""
    return {
        "amount": Decimal("100.00"),
        "currency": "BRL",
        "payment_method": "pix",
        "installments": 1,
        "splits": [
            {"recipient_id": "producer_1", "role": "Industria", "percent": Decimal("70.00")},
            {"recipient_id": "affiliate_9", "role": "distributor", "percent": Decimal("30.00")},
        ],
    }


@pytest.fixture
def service_card_data():
    """validated_data CARD 3x para uso direto na service (valores Decimal)."""
    return {
        "amount": Decimal("297.00"),
        "currency": "BRL",
        "payment_method": "card",
        "installments": 3,
        "splits": [
            {"recipient_id": "producer_1", "role": "Industria", "percent": Decimal("70.00")},
            {"recipient_id": "affiliate_9", "role": "distributor", "percent": Decimal("30.00")},
        ],
    }
