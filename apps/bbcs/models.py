import enum

from django.db import models

from apps.core.models import TimeStampedModel


class PaymentMethodEnum(enum.Enum):
    """
    Enumeração dos métodos de pagamento suportados pela plataforma.

    Cada membro carrega uma tupla de três valores: (code, label, allows_installments).
    Isso centraliza, em um único lugar, tanto os dados de exibição quanto a regra
    de negócio sobre parcelamento — evitando condicionais espalhadas pelo código.

    Membros:
        PIX  = ("pix",  "PIX",               False) — pagamento instantâneo, sem parcelamento e taxa 0%.
        CARD = ("card", "Cartão de Crédito",  True)  — aceita 1 a 12 parcelas com taxas progressivas.

    Propriedades:
        code (str): Valor canônico persistido no banco de dados (ex: "pix", "card").
        label (str): Rótulo legível para exibição (ex: "PIX", "Cartão de Crédito").
        allows_installments (bool): Indica se o método aceita parcelamento.

    Métodos de classe:
        choices() -> list[tuple]: Retorna lista de tuplas (code, label) compatível com
            o argumento `choices` de campos Django.
    """

    PIX = ("pix", "PIX", False)
    CARD = ("card", "Cartão de Crédito", True)

    @property
    def code(self):
        return self.value[0]

    @property
    def label(self):
        return self.value[1]

    @property
    def allows_installments(self):
        return self.value[2]

    @classmethod
    def choices(cls):
        return [(member.code, member.label) for member in cls]


class PaymentStatusEnum(enum.Enum):
    """
    Enumeração dos status de pagamento.

    Cada membro representa um status possível para um pagamento, com um código
    canônico e um rótulo legível. Centraliza os status válidos para evitar
    inconsistências e facilitar a manutenção.

    Membros:
        CAPTURED = ("captured", "Capturado") — pagamento confirmado e capturado.
        PENDING  = ("pending",  "Pendente")  — pagamento iniciado, aguardando confirmação.
        FAILED   = ("failed",   "Falhou")    — tentativa de pagamento que falhou.

    Propriedades:
        code (str): Valor canônico persistido no banco de dados (ex: "captured").
        label (str): Rótulo legível para exibição (ex: "Capturado").

    Métodos de classe:
        choices() -> list[tuple]: Retorna lista de tuplas (code, label) compatível com
            o argumento `choices` de campos Django.
    """

    CAPTURED = ("captured", "Capturado")
    PENDING = ("pending", "Pendente")
    FAILED = ("failed", "Falhou")

    @property
    def code(self):
        return self.value[0]

    @property
    def label(self):
        return self.value[1]

    @classmethod
    def choices(cls):
        return [(member.code, member.label) for member in cls]


class Payment(TimeStampedModel):
    """
    Representa uma transação de pagamento confirmada.

    Armazena o valor bruto, a taxa da plataforma e o valor líquido que será
    distribuído entre os recebedores via LedgerEntry. A idempotency_key garante
    que retries não dupliquem registros.

    Atributos:
        gross_amount (DecimalField): Valor bruto informado pelo cliente.
        platform_fee_amount (DecimalField): Taxa cobrada pela plataforma.
        net_amount (DecimalField): Valor líquido após desconto da taxa.
        payment_method (CharField): Método de pagamento (pix ou card).
        installments (PositiveSmallIntegerField): Número de parcelas (1–12). Padrão: 1.
        currency (CharField): Moeda da transação. Padrão: BRL.
        status (CharField): Status do pagamento. Padrão: captured.
        idempotency_key (CharField): Chave de idempotência fornecida pelo cliente.
        idempotency_payload_hash (CharField): Hash SHA-256 do payload original (opcional).
            Quando presente, a constraint unique_idempotency_key_payload_hash garante
            que a mesma chave não seja reutilizada com um payload diferente no banco.
            Se não for fornecido, a detecção de conflito ocorre apenas na camada de serviço.
    """

    gross_amount = models.DecimalField("Valor bruto", max_digits=12, decimal_places=2)
    platform_fee_amount = models.DecimalField("Taxa da plataforma", max_digits=12, decimal_places=2)
    net_amount = models.DecimalField("Valor líquido", max_digits=12, decimal_places=2)
    payment_method = models.CharField("Método de pagamento", max_length=10, blank=False, null=False,
                                      choices=PaymentMethodEnum.choices)
    installments = models.PositiveSmallIntegerField("Parcelas", default=1)
    currency = models.CharField("Moeda", max_length=3, default="BRL")
    status = models.CharField("Status", max_length=20, choices=PaymentStatusEnum.choices,
                              default=PaymentStatusEnum.CAPTURED)
    idempotency_key = models.CharField("Chave de idempotência", max_length=255, unique=True, db_index=True)
    idempotency_payload_hash = models.CharField("Hash do payload", max_length=64, blank=False, null=False)
    payload = models.JSONField("Payload original", blank=True, null=True)

    class Meta:
        verbose_name = "Pagamento"
        verbose_name_plural = "Pagamentos"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key", "idempotency_payload_hash"],
                name="unique_idempotency_key_payload_hash")
        ]


class LedgerEntry(TimeStampedModel):
    """
    Lançamento de recebível gerado a partir de um pagamento confirmado.

    Cada recebedor do split tem sua própria entrada no ledger, com o valor
    calculado sobre o net_amount do pagamento. Serve como base para auditoria
    e reconciliação financeira.

    Atributos:
        payment (ForeignKey): Pagamento ao qual este lançamento pertence.
        recipient_id (CharField): Identificador externo do recebedor.
        role (CharField): Papel do recebedor na transação (ex: producer, affiliate).
        percent (DecimalField): Percentual do split atribuído a este recebedor.
        amount (DecimalField): Valor calculado em reais para este recebedor.
    """

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="ledger_entries",
                                verbose_name="Pagamento")
    recipient_id = models.CharField("ID do recebedor", max_length=255)
    role = models.CharField("Papel", max_length=50)
    percent = models.DecimalField("Percentual", max_digits=5, decimal_places=2)
    amount = models.DecimalField("Valor", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Lançamento"
        verbose_name_plural = "Lançamentos"
        ordering = ["-created_at"]


class Plan(TimeStampedModel):
    """
    Plano de taxas e prazos aplicado a uma transação de pagamento.

    Armazena as regras financeiras de uma modalidade de cobrança: quais taxas
    incidem sobre cada método/parcela e em quantos dias o recebedor recebe o valor.
    A estrutura em JSONField permite flexibilidade para adicionar novas modalidades
    sem alterar o schema do banco.

    Estrutura esperada para `fee_table`:
        {
            "debito":    {"1": {"taxa": 2.99}},
            "credito":   {"1": {"taxa": 3.99}},
            "parcelado": {"1": {"taxa": 4.79}, "2": {"taxa": 4.79}, ..., "12": {"taxa": 4.79}}
        }

    Estrutura esperada para `settlement_table`:
        {
            "debito":    {"1": {"prazo": 1}},
            "credito":   {"1": {"prazo": 30}},
            "parcelado": {"1": {"prazo": 30}, "2": {"prazo": 60}, ..., "12": {"prazo": 360}}
        }

    Atributos:
        name (CharField): Nome identificador do plano (ex: "Padrão", "Premium").
        fee_table (JSONField): Tabela de taxas por modalidade e número de parcelas.
        settlement_table (JSONField): Tabela de prazos de liquidação por modalidade e parcela.
        is_default (BooleanField): Indica se este é o plano padrão da plataforma. Padrão: False.
    """

    name = models.CharField("Nome do plano", max_length=100, unique=True)
    fee_table = models.JSONField("Tabela de taxas", blank=False, null=False)
    settlement_table = models.JSONField("Tabela de prazos", blank=False, null=False)
    is_default = models.BooleanField("Plano padrão", default=False)

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"
        ordering = ["-created_at"]
