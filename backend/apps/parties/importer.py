"""Importing clients from a spreadsheet (B.3), all or nothing.

Columns in plain words, mapped to the client record: name (required), legal
name, GSTIN, GST type (optional: "registered", "composition", "SEZ",
"unregistered", "consumer", "overseas"; without it a GSTIN means registered
and no GSTIN unregistered), state (name or code; read from the GSTIN when
there is one), PAN, email, phone, address, city, PIN code. Each row then
passes the same checks as a client added on the screen. A GSTIN or a name
already among the clients (any case), or twice in the file, is refused.
"""

import re
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models.functions import Lower

from apps.core import sheets
from apps.core.imports import RowErrors, row_error, validate_rows
from apps.core.india import STATE_CODES
from apps.core.permissions import require
from apps.core.tenancy import Principal

from .models import Party

LAYOUT = sheets.Layout(
    columns={
        "display_name": ("name", "client", "client_name", "customer", "party", "party_name"),
        "legal_name": ("legal_name", "registered_name", "company_name"),
        "gstin": ("gstin", "gst_no", "gst_number", "gstin_uin"),
        "gst_type": ("gst_type", "gst_treatment", "registration_type"),
        "state": ("state", "state_code", "place"),
        "pan": ("pan", "pan_no"),
        "email": ("email", "e_mail", "email_id"),
        "phone": ("phone", "mobile", "phone_no", "mobile_no", "contact"),
        "line1": ("address", "address_line_1", "line1", "street"),
        "city": ("city", "town"),
        "pincode": ("pincode", "pin", "pin_code", "postal_code"),
        "payment_terms_days": ("payment_terms", "payment_terms_days", "credit_days", "due_days"),
    },
    required=("display_name",),
    numeric=("payment_terms_days",),
    sample_header=(
        "Name",
        "GSTIN",
        "GST type",
        "State",
        "Email",
        "Phone",
        "Address",
        "City",
        "PIN code",
    ),
    sample_rows=(
        (
            "Skyline Developers",
            "32AAACS4321K1ZO",
            "",
            "",
            "accounts@skyline.example",
            "9847012345",
            "MG Road",
            "Kochi",
            "682016",
        ),
        ("Anna Kurian", "", "Consumer", "Kerala", "", "9895011122", "", "", ""),
        ("Coastal Homes", "", "Unregistered", "Tamil Nadu", "", "", "", "", ""),
    ),
)

GST_TYPES = {
    "registered": "REGISTERED",
    "regular": "REGISTERED",
    "composition": "COMPOSITION",
    "sez": "SEZ",
    "unregistered": "UNREGISTERED",
    "consumer": "CONSUMER",
    "individual": "CONSUMER",
    "overseas": "OVERSEAS",
    "export": "OVERSEAS",
}
_STATE_BY_NAME = {re.sub(r"[^a-z]", "", name.lower()): code for code, name in STATE_CODES.items()}


def _state_code(text: str) -> str:
    """'Kerala' / 'kerala' / '32' / '3' -> '32'; anything else is kept, for the
    serializer to refuse."""
    if text.isdigit():
        return text.zfill(2)
    return _STATE_BY_NAME.get(re.sub(r"[^a-z]", "", text.lower()), text)


def to_party(values: dict[str, str]) -> dict[str, Any]:
    """A spreadsheet row in the shape PartyWriteSerializer reads."""
    gstin = values.get("gstin", "").replace(" ", "").upper()
    kind = values.get("gst_type", "").strip().lower()
    data: dict[str, Any] = {
        "display_name": values.get("display_name", ""),
        "gst_treatment": GST_TYPES.get(kind, kind.upper())
        if kind
        else ("REGISTERED" if gstin else "UNREGISTERED"),
        "is_customer": True,
    }
    for name in ("legal_name", "pan", "email", "payment_terms_days"):
        if values.get(name):
            data[name] = values[name]
    if gstin:
        data["gstin"] = gstin
    state = _state_code(values["state"]) if values.get("state") else None
    if state and not gstin:
        data["state_code"] = state
    if values.get("phone"):
        data["phone"] = re.sub(r"[\s()-]", "", values["phone"])
    if any(values.get(k) for k in ("line1", "city", "pincode")):
        data["billing_address"] = {
            "line1": values.get("line1", ""),
            "city": values.get("city", ""),
            "pincode": values.get("pincode", ""),
            "state_code": gstin[:2] if gstin else (state or ""),
        }
    return data


@dataclass
class PartyImport:
    dry_run: bool
    parties: list[Party]
    skipped_rows: list[int]
    ignored_columns: list[str]

    @property
    def count(self) -> int:
        return len(self.parties)


def import_parties(principal: Principal, data: bytes, *, dry_run: bool) -> PartyImport:
    from .serializers import PartyWriteSerializer

    require(principal, "masters.edit")
    sheet = sheets.read(data, LAYOUT)
    sheet.rows = [(row, to_party(values)) for row, values in sheet.rows]
    names = set(Party.objects.annotate(n=Lower("display_name")).values_list("n", flat=True))
    gstins = set(Party.objects.exclude(gstin=None).values_list("gstin", flat=True))
    seen_names: dict[str, int] = {}
    seen_gstins: dict[str, int] = {}

    def check(row: int, party: dict[str, Any]) -> RowErrors | None:
        name, gstin = str(party["display_name"]).strip().lower(), party.get("gstin")
        if name in names:
            return row_error("display_name", "A client with this name exists.", "party_exists")
        if gstin and gstin in gstins:
            return row_error("gstin", "A client with this GSTIN exists.", "gstin_exists")
        if name in seen_names:
            return row_error("display_name", f"Also on row {seen_names[name]}.", "duplicate_name")
        if gstin and gstin in seen_gstins:
            return row_error("gstin", f"Also on row {seen_gstins[gstin]}.", "duplicate_gstin")
        seen_names[name] = row
        if gstin:
            seen_gstins[gstin] = row
        return None

    rows = validate_rows(sheet, PartyWriteSerializer, check)
    parties = [
        Party(**fields, tenant_id=principal.tenant_id, created_by_id=principal.user_id)
        for _, fields in rows
    ]
    if dry_run:
        for party in parties:  # a preview: nothing was saved, so no id or timestamps
            party.id = party.created_at = party.updated_at = None
    else:
        with transaction.atomic():
            # One by one, as the client screen saves them: bulk_create mixing given values
            # and database defaults broke the GSTIN / state check here. Client lists are short.
            for party in parties:
                party.save()
    return PartyImport(dry_run, parties, sheet.skipped_rows, sheet.ignored_columns)
