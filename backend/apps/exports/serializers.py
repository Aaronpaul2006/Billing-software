from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.reports.serializers import BOOKS, PeriodSerializer

from . import services
from .models import Export, ExportFormat, ExportKind, ExportStatus

DATED_KINDS = {"DOCUMENTS", "PAYMENTS", "EXPENSES"}
SPREADSHEET_FORMATS = ["CSV", "XLSX"]


class ExportParamsSerializer(serializers.Serializer[Any]):
    """Invoice register, payments, expenses: `from` / `to` (default: this FY to
    today); invoice register and receivables: `book`."""

    from_ = serializers.DateField(required=False)
    to = serializers.DateField(required=False)
    book = serializers.ChoiceField(choices=BOOKS, default="ALL")

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")  # `from` is a Python keyword
        return fields


class ExportRequestSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=[k for k in ExportKind.values if k != "GSTR1"])
    format = serializers.ChoiceField(choices=SPREADSHEET_FORMATS)
    params = ExportParamsSerializer(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Stored params are complete (defaults filled in), so the file always
        says which period it covers."""
        given = attrs.get("params") or {"book": "ALL"}
        params: dict[str, Any] = {"book": given["book"]}
        if attrs["kind"] in DATED_KINDS:
            period = PeriodSerializer(data={k: v for k, v in given.items() if v is not None})
            if not period.is_valid():
                raise serializers.ValidationError({"params": period.errors})
            v = period.validated_data
            params = {"from": v["start"].isoformat(), "to": v["end"].isoformat()}
            if attrs["kind"] == "DOCUMENTS":
                params["book"] = v["book"]
        return {"kind": attrs["kind"], "format": attrs["format"], "params": params}


class ExportSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=ExportKind.choices)
    format = serializers.ChoiceField(choices=ExportFormat.choices)
    params = serializers.DictField()
    status = serializers.ChoiceField(choices=ExportStatus.choices)
    file_name = serializers.CharField(allow_null=True)
    size_bytes = serializers.IntegerField(allow_null=True)
    row_count = serializers.IntegerField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())
    error = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    download_url = serializers.SerializerMethodField(
        help_text="A link for 5 minutes; only when READY."
    )

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_download_url(self, obj: Export) -> str | None:
        return services.download_url(obj)


class ExportListSerializer(serializers.Serializer[Any]):
    results = ExportSerializer(many=True)
