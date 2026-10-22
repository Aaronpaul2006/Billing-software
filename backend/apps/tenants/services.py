"""Business profile, GST registrations and number series (docs/02-api-design.md §3)."""

import uuid
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import F

from apps.core.errors import Conflict, Invalid, NotFound
from apps.core.permissions import require
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document

from .models import DocumentSeries, GstRegistration, Tenant

NON_REGULAR_FORBIDDEN = frozenset({"TAX_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"})


# --- business profile ---------------------------------------------------------------


def get_tenant(principal: Principal) -> Tenant:
    require(principal, "tenant.read")
    return Tenant.objects.get(pk=principal.tenant_id)


def update_tenant(principal: Principal, expected: int, changes: dict[str, Any]) -> Tenant:
    require(principal, "tenant.settings")
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=principal.tenant_id)
        pan = changes.get("pan")
        if pan:
            gstins = GstRegistration.objects.filter(gstin__isnull=False).values_list(
                "gstin", flat=True
            )
            if any(gstin[2:12] != pan for gstin in gstins):
                raise Invalid(
                    "pan",
                    "This PAN does not match the business's GST registrations.",
                    code="pan_mismatch",
                )
        update_versioned(Tenant.objects, tenant.pk, expected, **changes)
    return Tenant.objects.get(pk=principal.tenant_id)


# --- GST registrations -----------------------------------------------------------------


def _registration(registration_id: uuid.UUID) -> GstRegistration:
    registration = GstRegistration.objects.filter(pk=registration_id).first()
    if registration is None:
        raise NotFound
    return cast(GstRegistration, registration)


def get_registration(principal: Principal, registration_id: uuid.UUID) -> GstRegistration:
    require(principal, "tenant.read")
    return _registration(registration_id)


def _make_default(registration_id: uuid.UUID) -> None:
    """Un-default every other registration (at most one default per tenant)."""
    GstRegistration.objects.filter(is_default=True).exclude(pk=registration_id).update(
        is_default=False, version=F("version") + 1
    )


def create_registration(principal: Principal, data: dict[str, Any]) -> GstRegistration:
    require(principal, "tenant.settings")
    gstin: str | None = data.get("gstin")
    tenant = Tenant.objects.get(pk=principal.tenant_id)
    if gstin and tenant.pan and gstin[2:12] != tenant.pan:
        raise Invalid(
            "gstin", "This GSTIN belongs to another PAN than the business's.", code="pan_mismatch"
        )
    try:
        with transaction.atomic():
            first = not GstRegistration.objects.exists()
            registration = GstRegistration(**{**data, "is_default": data["is_default"] or first})
            if registration.is_default:  # un-default the others before the insert
                _make_default(registration.pk)
            registration.save()
    except IntegrityError as exc:
        if gstin and GstRegistration.objects.filter(gstin=gstin).exists():
            raise Invalid("gstin", "This GSTIN is already registered.", code="gstin_taken") from exc
        raise
    return registration


def update_registration(
    principal: Principal, registration_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> GstRegistration:
    require(principal, "tenant.settings")
    with transaction.atomic():
        registration = _registration(registration_id)
        if registration.is_default and (
            changes.get("is_default") is False or changes.get("is_active") is False
        ):
            raise Conflict("Make another registration the default first.", code="default_required")
        if changes.get("is_default") and not changes.get("is_active", registration.is_active):
            raise Conflict("An inactive registration cannot be the default.", code="inactive")
        if changes.get("is_default"):
            _make_default(registration.pk)
        _check_lut(registration, changes)
        update_versioned(GstRegistration.objects, registration.pk, expected, **changes)
    return _registration(registration_id)


def _check_lut(registration: GstRegistration, changes: dict[str, Any]) -> None:
    arn = changes.get("lut_arn", registration.lut_arn)
    fy = changes.get("lut_fy_start_year", registration.lut_fy_start_year)
    if (arn is None) != (fy is None):
        field = "lut_fy_start_year" if fy is None else "lut_arn"
        raise Invalid(field, "Give the LUT's ARN and its financial year together.", code="required")
    if arn and registration.registration_type != "REGULAR":
        raise Invalid(
            "lut_arn", "Only regular registrations make zero-rated supplies.", code="not_allowed"
        )


# --- number series -------------------------------------------------------------------------

LOCKED_ONCE_USED = ("prefix", "pad_width", "next_number")


def series_in_use(series_id: uuid.UUID) -> bool:
    return bool(Document.objects.filter(series_id=series_id).exists())


def _series(series_id: uuid.UUID) -> DocumentSeries:
    series = DocumentSeries.objects.filter(pk=series_id).first()
    if series is None:
        raise NotFound
    return cast(DocumentSeries, series)


def get_series(principal: Principal, series_id: uuid.UUID) -> DocumentSeries:
    require(principal, "tenant.read")
    return _series(series_id)


def _check_one_active(
    registration_id: uuid.UUID, doc_type: str, fy: int, exclude: uuid.UUID | None = None
) -> None:
    active = DocumentSeries.objects.filter(
        gst_registration_id=registration_id, doc_type=doc_type, fy_start_year=fy, is_active=True
    )
    if exclude is not None:
        active = active.exclude(pk=exclude)
    if active.exists():
        raise Conflict(
            "Another series is already active for this registration, type and year.",
            code="active_series_exists",
        )


def create_series(principal: Principal, data: dict[str, Any]) -> DocumentSeries:
    require(principal, "tenant.settings")
    registration = GstRegistration.objects.filter(pk=data["gst_registration_id"]).first()
    if registration is None:  # also another tenant's: never reveal it exists
        raise Invalid("gst_registration_id", "No such GST registration.", code="not_found")
    if registration.registration_type != "REGULAR" and data["doc_type"] in NON_REGULAR_FORBIDDEN:
        raise Invalid(
            "doc_type",
            f"A {registration.registration_type} registration cannot issue {data['doc_type']};"
            " use BILL_OF_SUPPLY.",
            code="doc_type_not_allowed",
        )
    try:
        with transaction.atomic():
            if data["is_active"]:
                _check_one_active(registration.pk, data["doc_type"], data["fy_start_year"])
            series = DocumentSeries(**data)
            series.save()
    except IntegrityError as exc:
        raise Conflict(
            "A series with this prefix already exists for this registration, type and year.",
            code="series_exists",
        ) from exc
    return series


def update_series(
    principal: Principal, series_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> DocumentSeries:
    require(principal, "tenant.settings")
    try:
        with transaction.atomic():
            series = _series(series_id)
            touched = [
                f for f in LOCKED_ONCE_USED if f in changes and changes[f] != getattr(series, f)
            ]
            if touched and series_in_use(series.pk):
                raise Conflict(
                    f"Numbers were already issued from this series; {', '.join(touched)}"
                    " cannot change. Start a new series instead.",
                    code="series_in_use",
                )
            prefix = changes.get("prefix", series.prefix)
            pad_width = changes.get("pad_width", series.pad_width)
            if len(prefix) + pad_width > 16:
                raise Invalid(
                    "prefix", "Prefix plus digits may be at most 16 characters.", code="too_long"
                )
            if changes.get("is_active") and not series.is_active:
                _check_one_active(
                    series.gst_registration_id, series.doc_type, series.fy_start_year, series.pk
                )
            update_versioned(DocumentSeries.objects, series.pk, expected, **changes)
    except IntegrityError as exc:
        raise Conflict(
            "A series with this prefix already exists for this registration, type and year.",
            code="series_exists",
        ) from exc
    return _series(series_id)
