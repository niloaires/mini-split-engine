import math

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PersonalPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def get_page_size(self, request):
        page_size = request.query_params.get(self.page_size_query_param, DEFAULT_PAGE_SIZE)
        return min(int(page_size), self.max_page_size)

    def get_paginated_response(self, data):
        total_count = self.page.paginator.count
        page_size = self.get_page_size(self.request)
        total_pages = math.ceil(total_count / page_size)

        return Response(
            {
                "links": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "total": total_count,
                "page": int(self.request.GET.get("page", DEFAULT_PAGE)),
                "page_size": page_size,
                "total_pages": total_pages,
                "results": data,
            }
        )
