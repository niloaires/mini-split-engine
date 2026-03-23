import enum

from django.db import models

from apps.core.models import TimeStampedModel


class OutboxEventTypeEnum(enum.Enum):
    """
    Enumeração dos tipos de evento suportados pelo outbox.

    Cada membro representa um evento de domínio que deve ser propagado
    para consumidores externos após ser persistido. O padrão Outbox garante
    que o evento só seja publicado após a transação principal ser confirmada
    no banco, eliminando o risco de publicação sem persistência (ou vice-versa).

    Membros:
        PAYMENT_CAPTURED = ("payment_captured", "Pagamento capturado") —
            emitido quando um pagamento é confirmado e o split calculado.

    Propriedades:
        code (str): Valor canônico persistido no banco (ex: "payment_captured").
        label (str): Rótulo legível para exibição.

    Métodos de classe:
        choices() -> list[tuple]: Retorna lista de tuplas (code, label) compatível
            com o argumento `choices` de campos Django.
    """

    PAYMENT_CAPTURED = ("payment_captured", "Pagamento capturado")

    @property
    def code(self):
        return self.value[0]

    @property
    def label(self):
        return self.value[1]

    @classmethod
    def choices(cls):
        return [(member.code, member.label) for member in cls]


class OutboxEventStatusEnum(enum.Enum):
    """
    Enumeração dos status de processamento de um evento outbox.

    Controla o ciclo de vida do evento desde a criação até a publicação
    para o broker ou consumidor externo.

    Membros:
        PENDING   = ("pending",   "Pendente")   — evento criado, aguardando publicação.
        PUBLISHED = ("published", "Publicado")  — evento entregue ao consumidor externo.
        FAILED    = ("failed",    "Falhou")      — tentativa de publicação falhou.

    Propriedades:
        code (str): Valor canônico persistido no banco.
        label (str): Rótulo legível para exibição.

    Métodos de classe:
        choices() -> list[tuple]: Retorna lista de tuplas (code, label) compatível
            com o argumento `choices` de campos Django.
    """

    PENDING = ("pending", "Pendente")
    PUBLISHED = ("published", "Publicado")
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


class OutboxEvent(TimeStampedModel):
    """
    Evento de domínio persistido para publicação assíncrona (padrão Outbox).

    Garante que eventos críticos — como a captura de um pagamento — sejam
    registrados atomicamente junto à transação principal. Um worker externo
    (ou tarefa agendada) é responsável por ler os eventos com status "pending"
    e publicá-los no broker, atualizando o status para "published".

    Essa abordagem elimina o risco de inconsistência entre o banco e o sistema
    de mensageria: se a transação falhar, o evento não é criado; se o evento
    for criado, a transação foi confirmada.

    Atributos:
        type (CharField): Tipo do evento (ex: "payment_captured").
        payload (JSONField): Dados do evento serializados em JSON.
            Deve conter todas as informações necessárias para o consumidor
            processar o evento sem consultas adicionais ao banco.
        status (CharField): Status de publicação. Padrão: "pending".
        published_at (DateTimeField): Data e hora em que o evento foi publicado.
            Nulo enquanto o status for "pending" ou "failed".
    """

    type = models.CharField(
        "Tipo do evento",
        max_length=100,
        choices=OutboxEventTypeEnum.choices(),
        db_index=True,
    )
    payload = models.JSONField("Payload do evento")
    status = models.CharField(
        "Status",
        max_length=20,
        choices=OutboxEventStatusEnum.choices(),
        default=OutboxEventStatusEnum.PENDING.code,
        db_index=True,
    )
    published_at = models.DateTimeField("Publicado em", blank=True, null=True)

    class Meta:
        verbose_name = "Evento Outbox"
        verbose_name_plural = "Eventos Outbox"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="outbox_status_created_idx"),
        ]
