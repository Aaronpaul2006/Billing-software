"""Importing Tally's masters (Part B): what is new is added, what is already
here is skipped, and a master that does not pass the checks is listed with
the reason and left out. So the same file can be imported again safely.

Each client or vendor passes the same checks as one added on the screen
(PartyWriteSerializer), each item those of the catalog. "Already here" means a
party with the same name (any case) or GSTIN, or an item with the same name.
An address needs a city, which Tally has no field for: the last address line
is taken as the city when there are two or more; an address that still does
not pass is left out, and the party added without it.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.db.models.functions import Lower
from rest_framework.exceptions import ErrorDetail

from apps.catalog.models import CatalogItem
from apps.core.errors import Invalid
from apps.core.permissions import require
from apps.core.tenancy import Principal

from . import tally
from .importer import GST_TYPES, _state_code
from .models import Party
from .serializers import KINDS

MAX_ROWS = 500


@dataclass
class Row:
    kind: str
    name: str
    status: str  # NEW, EXISTS or PROBLEM
    message: str = ""
    detail: str = ""  # GSTIN and state, or HSN and GST %
    data: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Count:
    new: int = 0
    exists: int = 0
    problems: int = 0


@dataclass
class Plan:
    rows: list[Row]
    other_ledgers: int
    added: dict[str, int] = field(default_factory=dict)

    def count(self, kind: str) -> Count:
        statuses = [r.status for r in self.rows if r.kind == kind]
        return Count(statuses.count("NEW"), statuses.count("EXISTS"), statuses.count("PROBLEM"))


def _first_error(errors: Any) -> str:
    """The first message of a serializer's errors, with its field in words."""
    if isinstance(errors, dict):
        for name, value in errors.items():
            message = _first_error(value)
            if message:
                label = str(name).replace("_", " ")
                return message if name == "non_field_errors" else f"{label}: {message}"
    if isinstance(errors, list):
        for value in errors:
            if message := _first_error(value):
                return message
    if isinstance(errors, ErrorDetail | str):
        return str(errors)
    return ""


def _party_data(x: tally.Ledger) -> dict[str, Any]:
    kind = x.gst_type.strip().lower()
    if x.country and x.country.lower() not in ("india", "in"):
        treatment = "OVERSEAS"
    elif x.gstin and "sez" in kind:
        treatment = "SEZ"
    elif kind in GST_TYPES and not (kind.startswith("unregistered") and x.gstin):
        treatment = GST_TYPES[kind]
    else:
        treatment = "REGISTERED" if x.gstin else "UNREGISTERED"
    data: dict[str, Any] = {
        "display_name": x.name,
        "gst_treatment": treatment,
        "is_customer": x.kind == "CLIENT",
        "is_vendor": x.kind == "VENDOR",
    }
    if x.gstin and treatment != "OVERSEAS":
        data["gstin"] = x.gstin
    state = _state_code(x.state) if x.state else ""
    if state and "gstin" not in data and treatment != "OVERSEAS":
        data["state_code"] = state
    if x.mailing_name and x.mailing_name.lower() != x.name.lower():
        data["legal_name"] = x.mailing_name
    if x.pan:
        data["pan"] = x.pan
    if x.email:
        data["email"] = x.email.split(",")[0].split(";")[0].strip()
    if x.phone:
        data["phone"] = re.sub(r"[\s()-]", "", x.phone.split(",")[0])
    if x.credit_days:
        data["payment_terms_days"] = x.credit_days
    if len(x.address) >= 2 and treatment != "OVERSEAS":
        data["billing_address"] = {
            "line1": x.address[0],
            "line2": ", ".join(x.address[1:-1]),
            "city": x.address[-1],
            "pincode": x.pincode,
            "state_code": x.gstin[:2] if x.gstin else state,
        }
    return data


def _item_data(x: tally.StockItem) -> dict[str, Any]:
    data: dict[str, Any] = {"name": x.name}
    for key, value in (
        ("unit", x.unit),
        ("description", x.description),
        ("sac_hsn", x.hsn),
        ("gst_rate", x.gst_rate),
        ("default_rate", x.rate if x.rate not in ("", "0") else ""),
    ):
        if value:
            data[key] = value
    return data


def plan(principal: Principal, data: bytes) -> Plan:
    """What the file would add; nothing is saved."""
    from apps.catalog.serializers import CatalogItemWriteSerializer

    from .serializers import PartyWriteSerializer

    require(principal, "masters.edit")
    masters = tally.read(data)
    names = set(Party.objects.annotate(n=Lower("display_name")).values_list("n", flat=True))
    gstins = set(Party.objects.exclude(gstin=None).values_list("gstin", flat=True))
    item_names = set(CatalogItem.objects.annotate(n=Lower("name")).values_list("n", flat=True))
    rows: list[Row] = []

    for ledger in masters.ledgers:
        detail = " · ".join(v for v in (ledger.gstin, ledger.state) if v)
        key = ledger.name.lower()
        if key in names or (ledger.gstin and ledger.gstin in gstins):
            rows.append(Row(ledger.kind, ledger.name, "EXISTS", "Already here", detail))
            continue
        values = _party_data(ledger)
        s = PartyWriteSerializer(data=values)
        note = ""
        if not s.is_valid() and "billing_address" in s.errors:
            values.pop("billing_address")
            note = "Address left out: " + _first_error(s.errors["billing_address"])
            s = PartyWriteSerializer(data=values)
        if not s.is_valid():
            rows.append(Row(ledger.kind, ledger.name, "PROBLEM", _first_error(s.errors), detail))
            continue
        names.add(key)
        if ledger.gstin:
            gstins.add(ledger.gstin)
        rows.append(Row(ledger.kind, ledger.name, "NEW", note, detail, dict(s.validated_data)))

    for item in masters.items:
        detail = " · ".join(
            v
            for v in (item.hsn and f"HSN {item.hsn}", item.gst_rate and f"GST {item.gst_rate} %")
            if v
        )
        key = item.name.lower()
        if key in item_names:
            rows.append(Row("ITEM", item.name, "EXISTS", "Already here", detail))
            continue
        si = CatalogItemWriteSerializer(data=_item_data(item))
        if not si.is_valid():
            rows.append(Row("ITEM", item.name, "PROBLEM", _first_error(si.errors), detail))
            continue
        item_names.add(key)
        rows.append(Row("ITEM", item.name, "NEW", "", detail, dict(si.validated_data)))
    return Plan(rows, masters.other_ledgers)


def run(principal: Principal, data: bytes, kinds: list[str]) -> Plan:
    """Add the new masters of the kinds chosen, in one transaction."""
    result = plan(principal, data)
    chosen = [r for r in result.rows if r.status == "NEW" and r.kind in kinds]
    if not chosen:
        raise Invalid("kinds", "Nothing new to import.", code="nothing_new")
    with transaction.atomic():
        for r in chosen:
            if r.kind == "ITEM":
                CatalogItem.objects.create(**r.data, tenant_id=principal.tenant_id)
            else:
                Party.objects.create(
                    **r.data, tenant_id=principal.tenant_id, created_by_id=principal.user_id
                )
    result.added = {k: sum(1 for r in chosen if r.kind == k) for k in KINDS}
    return result
