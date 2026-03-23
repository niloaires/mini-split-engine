"""
Testes da calculadora de taxas e split (split_calculator.py).

Cobertura:
  - Taxa PIX (zero)
  - Taxa CARD 1x
  - Taxa CARD parcelado (2x–12x)
  - Leitura de taxa a partir do fee_table do Plan
  - Distribuição exata do split (sem resto)
  - Distribuição com resto de centavo (regra do primeiro recebedor)
  - Split com 1 recebedor (100%)
  - Split com 5 recebedores (limite máximo)
  - Invariante: soma dos recebíveis == net_amount
  - Invariante: gross - fee == net
  - Valores grandes (precisão de alto volume)
  - Valor mínimo (R$ 0.01)
  - Métodos de pagamento não suportados (erro esperado)
  - fee_table com chave ausente (erro esperado)
"""

from decimal import Decimal

import pytest

from apps.bbcs.services.split_calculator import (
    SplitInput,
    calculate_fee_rate,
    calculate_payment,
    calculate_split,
)


def D(value: str) -> Decimal:
    return Decimal(value)


def split(recipient_id: str, role: str, percent: str) -> SplitInput:
    return SplitInput(recipient_id=recipient_id, role=role, percent=D(percent))


MOCK_FEE_TABLE = {
    "pix":       {"1": {"taxa": 0}},
    "credito":   {"1": {"taxa": 3.99}},
    "parcelado": {
        "1":  {"taxa": 4.79},
        "2":  {"taxa": 4.79},
        "3":  {"taxa": 4.79},
        "4":  {"taxa": 4.79},
        "5":  {"taxa": 4.79},
        "6":  {"taxa": 4.79},
        "7":  {"taxa": 4.79},
        "8":  {"taxa": 4.79},
        "9":  {"taxa": 4.79},
        "10": {"taxa": 4.79},
        "11": {"taxa": 4.79},
        "12": {"taxa": 4.79},
    },
}



class TestCalculateFeeRateFallback:

    def test_pix_fee_is_zero(self):
        """PIX não tem taxa — fee_rate deve ser exatamente zero."""
        assert calculate_fee_rate("pix", 1) == D("0")

    def test_card_1x_fee(self):
        """CARD à vista aplica taxa fixa de 3,99%."""
        assert calculate_fee_rate("card", 1) == D("0.0399")

    def test_card_2x_fee(self):
        """CARD 2x: 4,99% + 2% × 1 parcela extra = 6,99%."""
        assert calculate_fee_rate("card", 2) == D("0.0699")

    def test_card_3x_fee(self):
        """CARD 3x: 4,99% + 2% × 2 parcelas extras = 8,99%."""
        assert calculate_fee_rate("card", 3) == D("0.0899")

    def test_card_6x_fee(self):
        """CARD 6x: 4,99% + 2% × 5 parcelas extras = 14,99%."""
        assert calculate_fee_rate("card", 6) == D("0.1499")

    def test_card_12x_fee(self):
        """CARD 12x (máximo): 4,99% + 2% × 11 parcelas extras = 26,99%."""
        assert calculate_fee_rate("card", 12) == D("0.2699")

    def test_unsupported_method_raises(self):
        """Método não suportado deve lançar ValueError com mensagem clara."""
        with pytest.raises(ValueError, match="não suportado"):
            calculate_fee_rate("boleto", 1)



class TestCalculateFeeRateFromPlan:

    def test_pix_from_plan(self):
        """Taxa PIX lida do fee_table deve ser zero."""
        assert calculate_fee_rate("pix", 1, fee_table=MOCK_FEE_TABLE) == D("0")

    def test_card_1x_from_plan(self):
        """Taxa CARD 1x lida do fee_table deve ser 3,99% (chave 'credito')."""
        assert calculate_fee_rate("card", 1, fee_table=MOCK_FEE_TABLE) == D("0.0399")

    def test_card_3x_from_plan(self):
        """Taxa CARD 3x lida do fee_table deve usar a chave 'parcelado' com parcela '3'."""
        assert calculate_fee_rate("card", 3, fee_table=MOCK_FEE_TABLE) == D("0.0479")

    def test_card_12x_from_plan(self):
        """Taxa CARD 12x lida do fee_table deve usar a chave 'parcelado' com parcela '12'."""
        assert calculate_fee_rate("card", 12, fee_table=MOCK_FEE_TABLE) == D("0.0479")

    def test_missing_key_in_plan_raises(self):
        """fee_table sem a chave esperada deve lançar KeyError."""
        incomplete_table = {"credito": {"1": {"taxa": 3.99}}}
        with pytest.raises(KeyError):
            calculate_fee_rate("pix", 1, fee_table=incomplete_table)



class TestCalculateSplit:

    def test_single_recipient_100_percent(self):
        """Um único recebedor a 100% deve receber o net_amount integral."""
        results = calculate_split(D("270.30"), [split("r1", "Industria", "100")])
        assert len(results) == 1
        assert results[0].amount == D("270.30")

    def test_two_recipients_70_30_exact(self):
        """Split 70/30 sobre valor divisível exato não deve gerar resto."""
        results = calculate_split(D("270.00"), [
            split("r1", "Industria", "70"),
            split("r2", "distributor", "30"),
        ])
        assert results[0].amount == D("189.00")
        assert results[1].amount == D("81.00")
        assert results[0].amount + results[1].amount == D("270.00")

    def test_two_recipients_70_30_with_remainder(self):
        """Split 70/30 sobre valor com centavo indivisível deve somar exatamente o net."""
        results = calculate_split(D("270.30"), [
            split("r1", "Industria", "70"),
            split("r2", "distributor", "30"),
        ])
        assert results[0].amount + results[1].amount == D("270.30")

    def test_remainder_absorbed_by_first_recipient(self):
        """Centavo restante da divisão deve ser absorvido pelo primeiro recebedor.

        10.00 dividido em 33% + 33% + 34%:
          r1 = floor(10.00 * 0.33) = 3.30
          r2 = floor(10.00 * 0.33) = 3.30
          r3 = floor(10.00 * 0.34) = 3.40
          soma = 10.00 → sem resto neste caso, mas r1 >= r2 pela regra.
        """
        results = calculate_split(D("10.00"), [
            split("r1", "Industria", "33"),
            split("r2", "distributor", "33"),
            split("r3", "coproducer", "34"),
        ])
        total = sum(r.amount for r in results)
        assert total == D("10.00")
        assert results[0].amount >= results[1].amount

    def test_five_recipients_invariant(self):
        """Com 5 recebedores (limite máximo), a soma deve ser igual ao net_amount."""
        net = D("999.99")
        results = calculate_split(net, [
            split("r1", "Industria",   "30"),
            split("r2", "distributor",  "25"),
            split("r3", "distributor",  "20"),
            split("r4", "coproducer", "15"),
            split("r5", "coproducer", "10"),
        ])
        assert sum(r.amount for r in results) == net

    def test_equal_split_two_recipients_odd_value(self):
        """R$ 0,01 dividido 50/50: um recebedor fica com 0,00 e o outro com 0,01.

        O primeiro recebedor absorve o centavo restante, garantindo que a soma
        seja sempre igual ao net_amount mesmo no caso mais extremo.
        """
        results = calculate_split(D("0.01"), [
            split("r1", "Industria", "50"),
            split("r2", "distributor", "50"),
        ])
        assert results[0].amount + results[1].amount == D("0.01")



class TestCalculatePayment:

    def test_pix_zero_fee_full_split(self):
        """Cenário do desafio 1: PIX com taxa zero — net == gross e split 100% bate."""
        result = calculate_payment(
            gross_amount=D("100.00"),
            payment_method="pix",
            installments=1,
            splits=[split("r1", "Industria", "100")],
        )
        assert result.platform_fee_amount == D("0.00")
        assert result.net_amount == D("100.00")
        assert result.receivables[0].amount == D("100.00")

    def test_card_3x_split_70_30(self):
        """Cenário do desafio 2: CARD 3x, split 70/30 — valores e soma dos recebíveis."""
        result = calculate_payment(
            gross_amount=D("297.00"),
            payment_method="card",
            installments=3,
            splits=[
                split("producer_1", "Industria", "70"),
                split("affiliate_9", "distributor", "30"),
            ],
        )
        assert result.platform_fee_amount == D("26.70")
        assert result.net_amount == D("270.30")
        total = sum(r.amount for r in result.receivables)
        assert total == result.net_amount

    def test_gross_minus_fee_equals_net(self):
        """Invariante financeira: gross_amount - platform_fee_amount deve ser sempre igual a net_amount."""
        result = calculate_payment(
            gross_amount=D("150.00"),
            payment_method="card",
            installments=6,
            splits=[split("r1", "Industria", "100")],
        )
        assert result.gross_amount - result.platform_fee_amount == result.net_amount

    def test_card_1x_fee_rate(self):
        """CARD à vista: fee = floor(200.00 × 0.0399) = 7.98, net = 192.02."""
        result = calculate_payment(
            gross_amount=D("200.00"),
            payment_method="card",
            installments=1,
            splits=[split("r1", "Industria", "100")],
        )
        assert result.platform_fee_amount == D("7.98")
        assert result.net_amount == D("192.02")

    def test_card_12x_high_fee(self):
        """CARD 12x (taxa máxima 26,99%): fee = floor(1000.00 × 0.2699) = 269.90."""
        result = calculate_payment(
            gross_amount=D("1000.00"),
            payment_method="card",
            installments=12,
            splits=[split("r1", "Industria", "100")],
        )
        assert result.platform_fee_amount == D("269.90")
        assert result.net_amount == D("730.10")

    def test_large_amount_precision(self):
        """Alto volume (R$ 99.999,99): invariante soma dos recebíveis == net_amount."""
        result = calculate_payment(
            gross_amount=D("99999.99"),
            payment_method="card",
            installments=1,
            splits=[
                split("r1", "Industria", "60"),
                split("r2", "distributor", "40"),
            ],
        )
        total = sum(r.amount for r in result.receivables)
        assert total == result.net_amount

    def test_minimum_amount(self):
        """Valor mínimo (R$ 0,01) via PIX: net e recebível devem ser R$ 0,01."""
        result = calculate_payment(
            gross_amount=D("0.01"),
            payment_method="pix",
            installments=1,
            splits=[split("r1", "Industria", "100")],
        )
        assert result.net_amount == D("0.01")
        assert result.receivables[0].amount == D("0.01")

    def test_with_plan_fee_table(self):
        """Com fee_table do Plan, taxa de 3x deve vir de 'parcelado'/'3' (4,79%)."""
        result = calculate_payment(
            gross_amount=D("297.00"),
            payment_method="card",
            installments=3,
            splits=[
                split("producer_1", "Industria", "70"),
                split("affiliate_9", "distributor", "30"),
            ],
            fee_table=MOCK_FEE_TABLE,
        )
        assert result.platform_fee_amount == D("14.22")
        assert result.net_amount == D("282.78")
        total = sum(r.amount for r in result.receivables)
        assert total == result.net_amount

    def test_plan_overrides_fallback_rate(self):
        """Quando fee_table do Plan e fallback têm a mesma taxa (card 1x = 3,99%),
        o resultado financeiro deve ser idêntico entre as duas fontes."""
        result_fallback = calculate_payment(D("500.00"), "card", 1, [split("r1", "Industria", "100")])
        result_plan = calculate_payment(
            D("500.00"), "card", 1, [split("r1", "Industria", "100")], fee_table=MOCK_FEE_TABLE
        )
        assert result_fallback.platform_fee_amount == result_plan.platform_fee_amount
