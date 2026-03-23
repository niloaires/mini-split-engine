"""
split_calculator.py — Service de cálculo de taxas e split de recebíveis.

Baseado na lógica de produção de um sistema real de pagamentos (Go), adaptado
para Python com Decimal para garantir precisão financeira em nível de centavos.

Estratégia de precisão:
- Todos os valores são manipulados como Decimal com quantização em 2 casas.
- Divisão por parcela usa ROUND_DOWN (floor), equivalente ao FloorMoney do Go,
  garantindo que nunca se distribua mais do que o total disponível.
- O resto (centavos que sobram da divisão) é absorvido inteiramente pela
  PRIMEIRA parcela/recebedor — mesma estratégia do código de referência.
  Isso garante que: soma(parcelas) == total e soma(recebedores) == net_amount.

Fonte de taxas:
- Quando um `fee_table` do model Plan é fornecido, as taxas são lidas dele.
- Quando não é fornecido, o calculator cai no fallback com as taxas fixas
  definidas pelo desafio técnico.

Estrutura esperada do fee_table (Plan.fee_table):
    {
        "pix":       {"1": {"taxa": 0}},
        "credito":   {"1": {"taxa": 3.99}},
        "parcelado": {"1": {"taxa": 4.79}, "2": {"taxa": 4.79}, ..., "12": {"taxa": 4.79}}
    }

Mapeamento payment_method + installments → chave do fee_table:
    pix,  qualquer → "pix"
    card, 1        → "credito"
    card, 2–12     → "parcelado"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

""""
Aqui em um contexto de desenvolvimento real, 
usaria variáveis de ambiente ou configuração centralizada para as taxas fixas,
"""
PIX_FEE_RATE = Decimal("0")
CARD_1X_FEE_RATE = Decimal("0.0399")
CARD_BASE_FEE_RATE = Decimal("0.0499")
CARD_INSTALLMENT_EXTRA_RATE = Decimal("0.02")

_PLAN_KEY_MAP: dict[tuple[str, bool], str] = {
    ("pix", False): "pix",
    ("card", False): "credito",
    ("card", True): "parcelado",
}



@dataclass
class SplitInput:
    """
    Entrada de um participante do split.

    Atributos:
        recipient_id (str): Identificador externo do recebedor.
        role (str): Papel do recebedor na transação (ex: "producer", "affiliate").
        percent (Decimal): Percentual do split. Deve ser entre 0 e 100 exclusive,
            e a soma de todos os percentuais deve ser exatamente 100.
    """

    recipient_id: str
    role: str
    percent: Decimal


@dataclass
class SplitResult:
    """
    Resultado calculado para um participante do split.

    Atributos:
        recipient_id (str): Identificador externo do recebedor.
        role (str): Papel do recebedor na transação.
        percent (Decimal): Percentual aplicado.
        amount (Decimal): Valor em reais calculado sobre o net_amount.
    """

    recipient_id: str
    role: str
    percent: Decimal
    amount: Decimal


@dataclass
class PaymentCalculation:
    """
    Resultado completo do cálculo de um pagamento.

    Atributos:
        gross_amount (Decimal): Valor bruto informado pelo cliente.
        fee_rate (Decimal): Taxa aplicada como fração decimal (ex: 0.0399).
        platform_fee_amount (Decimal): Valor da taxa em reais.
        net_amount (Decimal): Valor líquido após desconto da taxa.
        receivables (list[SplitResult]): Lista de recebíveis por participante.
    """

    gross_amount: Decimal
    fee_rate: Decimal
    platform_fee_amount: Decimal
    net_amount: Decimal
    receivables: list[SplitResult] = field(default_factory=list)


def _quantize(value: Decimal) -> Decimal:
    """Arredonda para 2 casas decimais com ROUND_HALF_UP."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _floor(value: Decimal) -> Decimal:
    """Trunca para 2 casas decimais sem arredondamento (equivalente a FloorMoney)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)



def _fee_rate_from_plan(fee_table: dict, payment_method: str, installments: int) -> Decimal:
    """
    Lê a taxa do fee_table do model Plan para o método e número de parcelas.

    Resolve a chave de busca via _PLAN_KEY_MAP:
        pix,  qualquer → "pix"
        card, 1        → "credito"
        card, 2–12     → "parcelado"

    O valor da taxa no fee_table é um percentual (ex: 3.99), convertido
    internamente para fração decimal (ex: 0.0399) antes de retornar.

    Args:
        fee_table: Dicionário do Plan.fee_table.
        payment_method: "pix" ou "card".
        installments: Número de parcelas (1–12).

    Returns:
        Taxa como Decimal (ex: Decimal("0.0399")).

    Raises:
        KeyError: Combinação de método/parcela não encontrada no fee_table.
    """
    is_installment = payment_method == "card" and installments > 1
    plan_key = _PLAN_KEY_MAP[(payment_method, is_installment)]
    taxa_percent = fee_table[plan_key][str(installments)]["taxa"]
    return Decimal(str(taxa_percent)) / Decimal("100")


def calculate_fee_rate(
    payment_method: str,
    installments: int,
    fee_table: dict | None = None,
) -> Decimal:
    """
    Retorna a taxa da plataforma como fração decimal para o método e parcelas.

    Quando `fee_table` é fornecido (lido do model Plan), a taxa é buscada nele.
    Caso contrário, aplica as taxas fixas definidas pelo desafio técnico:
        PIX:        0%
        CARD 1x:    3,99%
        CARD 2–12x: 4,99% + 2% × (installments - 1)

    Args:
        payment_method: "pix" ou "card".
        installments: Número de parcelas (1–12).
        fee_table: Dicionário do Plan.fee_table (opcional).

    Returns:
        Taxa como Decimal (ex: Decimal("0.0399")).

    Raises:
        ValueError: Método de pagamento não suportado (fallback).
        KeyError: Combinação não encontrada no fee_table (quando fornecido).
    """
    if fee_table is not None:
        return _fee_rate_from_plan(fee_table, payment_method, installments)

    # Fallback — taxas fixas do desafio
    if payment_method == "pix":
        return PIX_FEE_RATE

    if payment_method == "card":
        if installments == 1:
            return CARD_1X_FEE_RATE
        extra = CARD_INSTALLMENT_EXTRA_RATE * Decimal(installments - 1)
        return CARD_BASE_FEE_RATE + extra

    raise ValueError(f"Método de pagamento não suportado: {payment_method!r}")



def calculate_split(net_amount: Decimal, splits: list[SplitInput]) -> list[SplitResult]:
    """
    Distribui o net_amount entre os recebedores conforme os percentuais.

    Estratégia de centavos:
        Cada recebedor recebe floor(net_amount * percent / 100).
        O resto (net_amount - soma dos valores calculados) é somado
        inteiramente ao primeiro recebedor, garantindo que a soma dos
        recebíveis seja exatamente igual ao net_amount.

    Args:
        net_amount: Valor líquido a ser distribuído.
        splits: Lista de participantes com seus percentuais.

    Returns:
        Lista de SplitResult com os valores calculados por recebedor.
    """
    results: list[SplitResult] = []
    total_distributed = Decimal("0")

    for split in splits:
        amount = _floor(net_amount * split.percent / Decimal("100"))
        total_distributed += amount
        results.append(SplitResult(
            recipient_id=split.recipient_id,
            role=split.role,
            percent=split.percent,
            amount=amount,
        ))

    remainder = _quantize(net_amount - total_distributed)
    if remainder != Decimal("0") and results:
        results[0].amount = _quantize(results[0].amount + remainder)

    return results


def calculate_payment(
    gross_amount: Decimal,
    payment_method: str,
    installments: int,
    splits: list[SplitInput],
    fee_table: dict | None = None,
) -> PaymentCalculation:
    """
    Executa o cálculo completo de um pagamento: taxa, net e split.

    O cálculo segue a ordem:
        1. Determina a taxa — lida do fee_table do Plan se fornecido,
           ou pelas taxas fixas do desafio como fallback.
        2. Calcula platform_fee_amount = floor(gross_amount × fee_rate).
        3. Calcula net_amount = gross_amount - platform_fee_amount.
        4. Distribui net_amount entre os recebedores pelo split.

    Args:
        gross_amount: Valor bruto da transação.
        payment_method: "pix" ou "card".
        installments: Número de parcelas (1–12 para card, 1 para pix).
        splits: Lista de participantes com percentuais que somam 100.
        fee_table: Dicionário do Plan.fee_table (opcional). Quando fornecido,
            as taxas são lidas do plano em vez das constantes fixas.

    Returns:
        PaymentCalculation com todos os valores calculados.
    """
    fee_rate = calculate_fee_rate(payment_method, installments, fee_table=fee_table)
    platform_fee_amount = _floor(gross_amount * fee_rate)
    net_amount = _quantize(gross_amount - platform_fee_amount)

    receivables = calculate_split(net_amount, splits)

    return PaymentCalculation(
        gross_amount=gross_amount,
        fee_rate=fee_rate,
        platform_fee_amount=platform_fee_amount,
        net_amount=net_amount,
        receivables=receivables,
    )
