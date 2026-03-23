import uuid

from django.db import models


class ActiveObjects(models.Manager):
    """
    Gerenciador customizado para retornar apenas objetos ativos.

    Dessa forma, realizo soft deletes com a segurannça que o dado persistido será mantido.
    """

    def get_queryset(self):
        return super().get_queryset().filter(active=True)


class AllObjects(models.Manager):
    """ "

    Gerenciador customizado para retornar todos os objetos, independentemente do estado ativo."""

    def get_queryset(self):
        return super().get_queryset()


class TimeStampedModel(models.Model):
    """
    Modelo base abstrato com campos de auditoria e controle de ciclo de vida.

    Fornece campos comuns de rastreamento de tempo e estado para todos os modelos
    que herdam desta classe. Inclui suporte a gerenciadores customizados para
    filtrar registros ativos ou retornar todos os registros.

    Atributos:
        id (UUIDField): Identificador único universal, gerado automaticamente.
        created_at (DateTimeField): Data e hora de criação do registro.
        updated_at (DateTimeField): Data e hora da última atualização do registro.
        active (BooleanField): Indica se o registro está ativo. Padrão: True.
        objects (ActiveObjects): Gerenciador padrão que retorna apenas registros ativos.
        allobjects (AllObjects): Gerenciador alternativo que retorna todos os registros.

    Meta:
        abstract: True — esta classe não gera tabela própria no banco de dados.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, auto_created=True)
    created_at = models.DateTimeField("Created", auto_now_add=True, auto_now=False)
    updated_at = models.DateTimeField("Updated at", auto_now_add=False, auto_now=True)
    active = models.BooleanField("Active", default=True)
    objects = ActiveObjects()
    allobjects = AllObjects()

    class Meta:
        abstract = True
