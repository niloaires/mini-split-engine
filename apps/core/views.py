from drf_spectacular.plumbing import get_relative_url, set_query_parameters
from drf_spectacular.settings import spectacular_settings
from drf_spectacular.utils import extend_schema
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView


class SpectacularElementsView(APIView):
    renderer_classes = [TemplateHTMLRenderer]

    url_name = "schema"
    url = None
    template_name = "elements.html"
    title = spectacular_settings.TITLE

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        return Response(
            data={
                "title": self.title,
                "js_dist": "https://unpkg.com/@stoplight/elements/web-components.min.js",
                "css_dist": "https://unpkg.com/@stoplight/elements/styles.min.css",
                "schema_url": self._get_schema_url(request),
            },
            template_name=self.template_name,
        )

    def _get_schema_url(self, request):
        schema_url = self.url or get_relative_url(reverse(self.url_name, request=request))
        return set_query_parameters(
            url=schema_url,
            lang=request.GET.get("lang"),
            version=request.GET.get("version"),
        )


class SpectacularRapiDocView(APIView):
    renderer_classes = [TemplateHTMLRenderer]

    url_name = "schema"
    url = None
    template_name = "rapidoc.html"
    title = spectacular_settings.TITLE

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        return Response(
            data={
                "title": self.title,
                "dist": "https://cdn.jsdelivr.net/npm/rapidoc@latest",
                "schema_url": self._get_schema_url(request),
            },
            template_name=self.template_name,
        )

    def _get_schema_url(self, request):
        schema_url = self.url or get_relative_url(reverse(self.url_name, request=request))
        return set_query_parameters(
            url=schema_url,
            lang=request.GET.get("lang"),
            version=request.GET.get("version"),
        )
