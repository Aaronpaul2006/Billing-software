"""What every spreadsheet import shares (items, clients, bill lines): the
upload request, row-by-row validation with spreadsheet row numbers in the
errors (`rows[7].rate`), and the sample file download. The BOQ import (S.2)
works the same way; apps.core.sheets reads the files.

Imports are all or nothing: one bad row and nothing is saved; `dry_run`
validates and previews without saving.
"""

from collections.abc import Callable
from typing import Any, cast

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError

from . import sheets
from .errors import Invalid

MAX_ROW_ERRORS = 100

RowErrors = dict[str, list[ErrorDetail]]  # field -> errors, as a serializer gives them


class ImportRequestSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(help_text="CSV (UTF-8) or .xlsx, at most 5 MB and 5,000 rows.")
    dry_run = serializers.BooleanField(
        default=False, help_text="Validate and preview; save nothing."
    )


class SampleQuerySerializer(serializers.Serializer[Any]):
    # not `format`: DRF reads ?format= to pick a renderer
    type = serializers.ChoiceField(choices=["xlsx", "csv"], default="xlsx")


def upload_bytes(upload: Any) -> bytes:
    if upload.size > sheets.MAX_BYTES:
        raise Invalid("file", "At most 5 MB per import.", code="file_too_large")
    return bytes(upload.read())


def row_error(field: str, message: str, code: str) -> RowErrors:
    return {field: [ErrorDetail(message, code=code)]}


def validate_rows(
    sheet: sheets.Sheet,
    serializer: type[serializers.Serializer[Any]],
    check: Callable[[int, dict[str, Any]], RowErrors | None] | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    """Each row through the same serializer as a single create, then `check`
    (duplicates and the like). Raises the 422 with every row's errors (at most
    100); returns (row number, validated data)."""
    errors: dict[int, Any] = {}
    valid: list[tuple[int, dict[str, Any]]] = []
    for row, values in sheet.rows:
        if len(errors) >= MAX_ROW_ERRORS:
            break
        s = serializer(data=values)
        if not s.is_valid():
            errors[row] = s.errors
            continue
        data = dict(s.validated_data)
        problem = check(row, data) if check else None
        if problem:
            errors[row] = problem
            continue
        valid.append((row, data))
    if errors:
        raise ValidationError(cast(Any, {"rows": errors}))  # {row number: errors}, as many=True
    if not valid:
        raise Invalid("file", "No rows to import found.", code="no_rows")
    return valid


def sample_response(layout: sheets.Layout, fmt: str, name: str) -> HttpResponse:
    content, content_type = sheets.sample(layout, fmt)
    return HttpResponse(
        content,
        content_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'},
    )
