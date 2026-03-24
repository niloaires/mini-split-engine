from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins
from rest_framework.viewsets import GenericViewSet

from apps.payees.models import Recipient
from apps.payees.serializers import RecipientSerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Recebedores"],
        summary="Listar recebedores",
        description="Retorna a lista paginada de recebedores ativos cadastrados na plataforma.",
        parameters=[
            OpenApiParameter(name="page", type=int, description="Número da página."),
            OpenApiParameter(name="page_size", type=int, description="Itens por página (máx. 100)."),
        ],
    ),
    retrieve=extend_schema(
        tags=["Recebedores"],
        summary="Detalhar recebedor",
        description="Retorna os dados de um recebedor pelo seu ID interno.",
    ),
)
class RecipientViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet):
    serializer_class = RecipientSerializer
    queryset = Recipient.objects.filter(active=True).order_by("name")
