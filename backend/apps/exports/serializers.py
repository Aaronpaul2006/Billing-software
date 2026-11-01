from datetime import date
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.parties.models import Party
from apps.projects.models import Project
from apps.reports.serializers import BOOKS, PeriodSerializer
from apps.tenants.models import GstRegistration

from . import services
from .models import Export, ExportFormat, ExportKind, ExportStatus

DATED_KINDS = {"DOCUMENTS", "PAYMENTS", "EXPENSES"}
FIRST_GSTR1_PERIOD = "2025-05"  # the HSN summary split into B2B / B2C from May 2025


class ExportParamsSerializer(serializers.Serializer[Any]):
    """Invoice register, payments, expenses: `from` / `to` (default: this FY to
    today); invoice register and receivables: `book`; GSTR-1:
    `gst_registration_id` and `period` (YYYY-MM)."""

    from_ = serializers.DateField(required=False)
    to = serializers.DateField(required=False)
    book = serializers.ChoiceField(choices=BOOKS, default="ALL")
    gst_registration_id = serializers.UUIDField(required=False)
    project_id = serializers.UUIDField(required=False, help_text="BOQ: the project.")
    party_id = serializers.UUIDField(required=False, help_text="STATEMENT: the client.")
    period = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", required=False)

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")  # `from` is a Python keyword
        return fields


class ExportRequestSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=ExportKind.values)
    format = serializers.ChoiceField(
        choices=ExportFormat.values,
        help_text="GSTR-1: JSON; statement: CSV, XLSX or PDF; everything else: CSV or XLSX.",
    )
    params = ExportParamsSerializer(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Stored params are complete (defaults filled in), so the file always
        says which period it covers."""
        given = attrs.get("params") or {"book": "ALL"}
        if (attrs["kind"] == "GSTR1") != (attrs["format"] == "JSON"):
            raise serializers.ValidationError(
                {"format": "GSTR-1 is a JSON file; the registers are CSV or XLSX."},
                code="invalid_format",
            )
        if attrs["format"] == "PDF" and attrs["kind"] != "STATEMENT":
            raise serializers.ValidationError(
                {"format": "Only a statement of account is made as a PDF."},
                code="invalid_format",
            )
        if attrs["kind"] == "GSTR1":
            return {"kind": "GSTR1", "format": "JSON", "params": self._gstr1(given)}
        if attrs["kind"] == "STATEMENT":
            return {
                "kind": "STATEMENT",
                "format": attrs["format"],
                "params": self._statement(given),
            }
        if attrs["kind"] == "BOQ":
            if not given.get("project_id"):
                raise serializers.ValidationError({"params.project_id": "Choose the project."})
            project = Project.objects.filter(pk=given["project_id"]).first()  # RLS: own only
            if project is None:
                raise serializers.ValidationError({"params.project_id": "No such project."})
            return {
                "kind": "BOQ",
                "format": attrs["format"],
                "params": {"project_id": str(project.pk)},
            }
        if attrs["kind"] == "PROJECTS":
            return {"kind": "PROJECTS", "format": attrs["format"], "params": {}}
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

    def _statement(self, given: dict[str, Any]) -> dict[str, Any]:
        if not given.get("party_id"):
            raise serializers.ValidationError({"params.party_id": "Choose the client."})
        party = Party.objects.filter(pk=given["party_id"]).first()  # RLS: own only
        if party is None:
            raise serializers.ValidationError({"params.party_id": "No such client."})
        dates = {k: given[k] for k in ("from", "to") if given.get(k) is not None}
        period = PeriodSerializer(data=dates)
        if not period.is_valid():
            raise serializers.ValidationError({"params": period.errors})
        v = period.validated_data
        return {
            "party_id": str(party.pk),
            "from": v["start"].isoformat(),
            "to": v["end"].isoformat(),
        }

    def _gstr1(self, given: dict[str, Any]) -> dict[str, Any]:
        errors: dict[str, str] = {}
        registration = None
        if not given.get("gst_registration_id"):
            errors["params.gst_registration_id"] = "Choose the GST registration."
        else:
            registration = GstRegistration.objects.filter(pk=given["gst_registration_id"]).first()
            if registration is None:
                errors["params.gst_registration_id"] = "No such GST registration."
            elif registration.registration_type != "REGULAR":
                errors["params.gst_registration_id"] = (
                    "Only regular registrations file GSTR-1 (composition files CMP-08)."
                )
        period = given.get("period")
        this_month = timezone.localdate().replace(day=1)
        if not period:
            errors["params.period"] = "Choose the month (YYYY-MM)."
        elif period < FIRST_GSTR1_PERIOD:
            errors["params.period"] = "Months from May 2025 only."
        elif date.fromisoformat(f"{period}-01") > this_month:
            errors["params.period"] = "That month has not started yet."
        if errors or registration is None:
            raise serializers.ValidationError(errors, code="invalid")
        return {"gst_registration_id": str(registration.pk), "period": period}


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
