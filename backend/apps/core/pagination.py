"""Cursor pagination (docs/02-api-design.md §1): `?limit=50&cursor=...`.

Response: {"results": [...], "next_cursor": "..." | null}. Cursors are opaque
and stable under inserts. Default ordering is by id (UUIDv7, creation time),
newest first; views may allow other orderings via `ordering_fields`.
"""

from typing import Any
from urllib.parse import parse_qs, urlparse

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class CursorPage(CursorPagination):
    page_size = 25
    page_size_query_param = "limit"
    max_page_size = 100
    cursor_query_param = "cursor"
    ordering = "-id"

    def _next_cursor(self) -> str | None:
        link = self.get_next_link()
        if not link:
            return None
        return parse_qs(urlparse(link).query).get(self.cursor_query_param, [None])[0]

    def get_paginated_response(self, data: Any) -> Response:
        return Response({"results": data, "next_cursor": self._next_cursor()})

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["results", "next_cursor"],
            "properties": {
                "results": schema,
                "next_cursor": {"type": ["string", "null"], "description": "Pass as ?cursor="},
            },
        }
