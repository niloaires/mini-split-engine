import enum

from django.db import models

from apps.core.models import TimeStampedModel


class RecipientRoleEnum(enum.Enum):
    """
    Enumeração dos papéis possíveis de um recebedor na plataforma.

    Cada membro carrega uma tupla (code, label), centralizando tanto o valor
    persistido no banco quanto o rótulo de exibição — seguindo o mesmo padrão
    de PaymentMethodEnum em bbcs.

    Membros:
        PRODUCER   = ("producer",   "Produtor")   — criador principal do produto.
        AFFILIATE  = ("affiliate",  "Afiliado")   — parceiro de divulgação com comissão.
        COPRODUTOR = ("coproducer", "Coprodutor") — produtor secundário com participação no split.

    Propriedades:
        code (str): Valor canônico persistido no banco (ex: "producer").
        label (str): Rótulo legível para exibição (ex: "Produtor").

    Métodos de classe:
        choices() -> list[tuple]: Retorna lista de tuplas (code, label) compatível com
            o argumento `choices` de campos Django.
    """

    PRODUCER = ("Industria", "Indústria")
    DISTRIBUTOR = ("distributor", "Distribuidor")
    STOREKEEPER = ("revenda", "Revenda")

    @property
    def code(self):
        return self.value[0]

    @property
    def label(self):
        return self.value[1]

    @classmethod
    def choices(cls):
        return [(member.code, member.label) for member in cls]


class Recipient(TimeStampedModel):
    """
    Representa um participante elegível a receber parte do split de um pagamento.

    Um recebedor é cadastrado previamente na plataforma e referenciado pelo seu
    `external_id` nos splits de cada transação. Isso permite rastrear histórico
    de recebimentos, aplicar regras por papel e desacoplar o cadastro do
    participante da lógica de pagamento.

    Atributos:
        name (CharField): Nome completo ou razão social do recebedor.
        document (CharField): CPF ou CNPJ do recebedor (opcional, para fins de KYC/compliance).
        email (EmailField): E-mail de contato do recebedor (opcional).
        role (CharField): Papel padrão do recebedor na plataforma.
        external_id (CharField): Identificador externo usado como referência
            nos splits da API (campo `recipient_id` do payload). Único e indexado.
        bank_account (JSONField): Dados bancários para liquidação (opcional).
            Utilizado como JSONField para dar celeridade à implementação do desafio.
            Em produção, o mais adequado seria uma tabela própria (ex: BankAccount)
            com FK para Recipient, garantindo rastreabilidade completa de mudanças
            de conta ao longo do tempo (histórico de alterações, auditoria, rollback).
            Exemplo de estrutura atual:
                {"bank": "001", "agency": "0001", "account": "12345-6", "type": "checking"}
    """

    name = models.CharField("Nome", max_length=255)
    document = models.CharField("CPF/CNPJ", max_length=18, blank=False, null=False)
    email = models.EmailField("E-mail", blank=True, null=True)
    role = models.CharField("Papel", max_length=20, choices=RecipientRoleEnum.choices())
    external_id = models.CharField("ID externo", max_length=255, unique=True, db_index=True)
    bank_account = models.JSONField("Dados bancários", blank=True, null=True)

    class Meta:
        verbose_name = "Recebedor"
        verbose_name_plural = "Recebedores"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "external_id"],
                name="unique_recipient_document_external_id",
            )
        ]
