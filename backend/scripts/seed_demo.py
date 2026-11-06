"""Fill a demo business with sample data, through the API like the web app.

For a local PC only (the dev stack: API on 127.0.0.1:8000, Mailpit on 8025):

    uv run python scripts/seed_demo.py --email you@example.com

The password comes from --password or DEMO_PASSWORD (asked for otherwise).
A new email is signed up as the owner of "Demo Constructions": its address is
confirmed from Mailpit and 2-step sign-in is turned on; the authenticator key
and the recovery codes are printed once, so keep them. For an existing
account with 2-step sign-in, give its key with --totp-secret or
DEMO_TOTP_SECRET. A business that already has a GST registration is left
alone (no duplicates). What to try afterwards: docs/05-demo.md.
"""

import argparse
import getpass
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

import pyotp
from PIL import Image, ImageDraw

Json = dict[str, Any]


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token = ""

    def call(
        self, method: str, path: str, body: Json | None = None, match: int | None = None
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if method == "POST":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        if match is not None:
            headers["If-Match"] = f'"v{match}"'
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data, headers, method=method)  # noqa: S310 - local API
        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310 - local API
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path}: {exc.code} {exc.read().decode()[:500]}") from exc
        return json.loads(raw) if raw else {}


def gstin(state: str, pan: str) -> str:
    """A GSTIN with a correct check character."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    first14 = f"{state}{pan}1Z"
    total = 0
    for i, c in enumerate(first14):
        product = chars.index(c) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return first14 + chars[(36 - total % 36) % 36]


def fresh_code(secret: str) -> str:
    """A code from a new 30-second step: each code is accepted once."""
    step = int(time.time()) // 30
    while int(time.time()) // 30 == step:
        time.sleep(1)
    return pyotp.TOTP(secret).now()


def sign_up(api: Api, mailpit: str, email: str, password: str) -> str:
    """A new owner account with its email confirmed and 2-step sign-in on."""
    signed = api.call(
        "POST",
        "/auth/signup",
        {
            "email": email,
            "password": password,
            "full_name": "Demo Owner",
            "business_name": "Demo Constructions",
        },
    )
    api.token = signed["access_token"]
    query = urllib.parse.quote(f"to:{email}")
    messages: list[Json] = []
    for _ in range(30):  # the worker sends the confirmation email a moment later
        with urllib.request.urlopen(f"{mailpit}/api/v1/search?query={query}") as r:  # noqa: S310
            messages = json.loads(r.read())["messages"]
        if messages:
            break
        time.sleep(1)
    if not messages:
        raise SystemExit("The confirmation email did not arrive: is the worker running?")
    with urllib.request.urlopen(f"{mailpit}/api/v1/message/{messages[0]['ID']}") as r:  # noqa: S310
        text = json.loads(r.read())["Text"]
    token = re.search(r"verify-email\?token=(\S+)", text)
    if token is None:
        raise SystemExit("No email confirmation link found in Mailpit.")
    api.call("POST", "/auth/verify-email", {"token": urllib.parse.unquote(token.group(1))})
    secret: str = api.call("POST", "/auth/mfa/setup")["secret"]
    enabled = api.call("POST", "/auth/mfa/enable", {"code": pyotp.TOTP(secret).now()})
    print(f"Signed up {email}. Authenticator key (time-based): {secret}")
    print("Recovery codes, each works once:", ", ".join(enabled["recovery_codes"]))
    return secret


def sign_in(api: Api, email: str, password: str, secret: str) -> None:
    api.token = ""
    login = api.call("POST", "/auth/login", {"email": email, "password": password})
    if "mfa_token" not in login:
        api.token = login["access_token"]
        return
    if not secret:
        raise SystemExit("This account has 2-step sign-in: pass --totp-secret.")
    verified = api.call(
        "POST", "/auth/mfa/verify", {"mfa_token": login["mfa_token"], "code": fresh_code(secret)}
    )
    api.token = verified["access_token"]


def logo_png() -> bytes:
    image = Image.new("RGB", (360, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((6, 6, 114, 114), fill=(30, 64, 120))
    draw.text((34, 44), "DC", fill="white", font_size=36)
    draw.text((130, 34), "Demo", fill=(30, 64, 120), font_size=30)
    draw.text((130, 68), "Constructions", fill=(90, 90, 90), font_size=22)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def upload(api: Api, name: str, data: bytes) -> str:
    started = api.call(
        "POST",
        "/attachments",
        {"filename": name, "content_type": "image/png", "size_bytes": len(data)},
    )
    put = urllib.request.Request(  # noqa: S310 - the local storage's upload link
        started["upload_url"], data, started["upload_headers"], method="PUT"
    )
    urllib.request.urlopen(put).read()  # noqa: S310 - local storage
    attachment_id: str = started["attachment"]["id"]
    api.call("POST", f"/attachments/{attachment_id}/complete")
    for _ in range(30):  # the worker checks the file
        if api.call("GET", f"/attachments/{attachment_id}")["status"] == "AVAILABLE":
            return attachment_id
        time.sleep(1)
    raise SystemExit("The logo was not checked in time: is the worker running?")


ITEMS = [
    ("RCC M25 concrete", "cum", "9954", "6800.00", "18"),
    ("Brick masonry in CM 1:6", "cum", "9954", "5200.00", "18"),
    ("Plastering 12 mm, CM 1:4", "sqm", "9954", "310.00", "18"),
    ("Vitrified tile flooring 600x600", "sqm", "9954", "1150.00", "18"),
    ("Interior painting, two coats", "sqm", "9954", "95.00", "18"),
    ("TMT steel Fe500D", "MT", "7214", "62000.00", "18"),
    ("Cement OPC 53 grade", "bag", "2523", "380.00", "28"),
]


def seed(api: Api) -> None:
    if api.call("GET", "/gst-registrations")["results"]:
        raise SystemExit("This business already has a GST registration: nothing added.")
    tenant = api.call("GET", "/tenant")
    api.call(
        "PATCH",
        "/tenant",
        {"trade_name": "Demo Constructions", "pan": "AAKFD1234B"},
        match=tenant["version"],
    )
    reg = api.call(
        "POST",
        "/gst-registrations",
        {
            "registration_type": "REGULAR",
            "gstin": gstin("32", "AAKFD1234B"),
            "legal_name": "Demo Constructions",
            "trade_name": "Demo Constructions",
            "is_default": True,
            "address": {
                "line1": "2nd Floor, Pearl Plaza, Seaport-Airport Road",
                "city": "Kochi",
                "state_code": "32",
                "pincode": "682021",
            },
        },
    )
    for doc_type, prefix in [
        ("TAX_INVOICE", "INV/"),
        ("QUOTATION", "QT/"),
        ("PROFORMA", "PI/"),
        ("CREDIT_NOTE", "CN/"),
        ("DEBIT_NOTE", "DN/"),
    ]:
        api.call(
            "POST",
            "/document-series",
            {
                "gst_registration_id": reg["id"],
                "doc_type": doc_type,
                "fy_start_year": 2026,
                "prefix": prefix,
            },
        )

    def party(**kw: Any) -> Json:
        result: Json = api.call("POST", "/parties", {"is_customer": True, **kw})
        return result

    def address(line1: str, city: str, state: str, pin: str) -> Json:
        return {"line1": line1, "city": city, "state_code": state, "pincode": pin}

    skyline = party(
        display_name="Skyline Developers",
        legal_name="Skyline Developers Pvt Ltd",
        gst_treatment="REGISTERED",
        gstin=gstin("32", "AABCS4321K"),
        pan="AABCS4321K",
        state_code="32",
        email="accounts@skyline.example",
        phone="9847012345",
        payment_terms_days=30,
        billing_address=address("Skyline House, MG Road", "Ernakulam", "32", "682016"),
    )
    green = party(
        display_name="Green Valley Homes",
        legal_name="Green Valley Homes LLP",
        gst_treatment="REGISTERED",
        gstin=gstin("29", "AAJFG5678L"),
        pan="AAJFG5678L",
        state_code="29",
        email="finance@greenvalley.example",
        phone="9845098450",
        payment_terms_days=45,
        billing_address=address("14, Outer Ring Road", "Bengaluru", "29", "560103"),
    )
    anil = party(
        display_name="Anil Kumar",
        gst_treatment="CONSUMER",
        state_code="32",
        email="anil.kumar@example.com",
        phone="9446012345",
        payment_terms_days=15,
        billing_address=address("Anugraha, Palarivattom", "Kochi", "32", "682025"),
    )
    lakshmi = party(
        display_name="Lakshmi Traders",
        gst_treatment="UNREGISTERED",
        pan="AAFFL1234K",
        state_code="32",
        phone="9387012345",
        billing_address=address("Market Road", "Thrissur", "32", "680001"),
    )

    def project(**kw: Any) -> Json:
        result: Json = api.call("POST", "/projects", {"gst_registration_id": reg["id"], **kw})
        return result

    tower = project(
        code="SKY-TOWER",
        name="Skyline Towers, Kakkanad",
        client_party_id=skyline["id"],
        site_state_code="32",
        contract_value="5000000.00",
        retention_pct="5",
        income_tax_tds_pct="2",
        start_date="2026-06-01",
        site_address=address("Infopark Phase 2", "Kakkanad", "32", "682042"),
    )
    villas = project(
        code="GV-VILLAS",
        name="Green Valley Villas, Bengaluru",
        client_party_id=green["id"],
        site_state_code="29",
        contract_value="3200000.00",
        retention_pct="5",
        income_tax_tds_pct="2",
        start_date="2026-07-15",
        site_address=address("Sarjapur Road", "Bengaluru", "29", "562125"),
    )
    house = project(
        code="ANIL-HOUSE",
        name="Anil's house renovation",
        client_party_id=anil["id"],
        site_state_code="32",
        contract_value="850000.00",
        start_date="2026-10-20",
    )

    items = {
        name: api.call(
            "POST",
            "/catalog-items",
            {"name": name, "unit": unit, "sac_hsn": hsn, "default_rate": rate, "gst_rate": gst},
        )
        for name, unit, hsn, rate, gst in ITEMS
    }

    def line(name: str, qty: str | None = None, **kw: Any) -> Json:
        item = items[name]
        out: Json = {
            "catalog_item_id": item["id"],
            "description": name,
            "sac_hsn": item["sac_hsn"],
            "unit": item["unit"],
            "rate": item["default_rate"],
            "gst_rate": item["gst_rate"],
        }
        if qty is not None:
            out["quantity"] = qty
        return {**out, **kw}

    api.call(
        "PATCH",
        "/tenant/print-settings",
        {
            "layout": "DETAILED",
            "logo_attachment_id": upload(api, "logo.png", logo_png()),
            "bank_account_name": "Demo Constructions",
            "bank_name": "State Bank of India",
            "bank_account_number": "41230098765",
            "bank_ifsc": "SBIN0070123",
            "bank_branch": "Kakkanad",
            "upi_id": "democonstructions@okaxis",
            "default_terms": "Payment within the due date by bank transfer or UPI.\n"
            "Interest at 18% a year on payments made after the due date.",
        },
        match=api.call("GET", "/tenant/print-settings")["version"],
    )

    def draft(**kw: Any) -> Json:
        result: Json = api.call("POST", "/documents", {"doc_type": "TAX_INVOICE", **kw})
        return result

    def issue(doc: Json) -> Json:
        result: Json = api.call("POST", f"/documents/{doc['id']}/issue", {}, match=doc["version"])
        return result

    walls = [
        {"description": "Wall A", "nos": "2", "length": "12.5", "breadth": "0.23", "height": "3.1"},
        {"description": "Wall B", "nos": "4", "length": "8.2", "breadth": "0.23", "height": "3.1"},
        {
            "description": "Door openings",
            "nos": "6",
            "length": "1.0",
            "breadth": "0.23",
            "height": "2.1",
            "deduct": True,
        },
    ]
    inv1 = issue(
        draft(
            party_id=skyline["id"],
            project_id=tower["id"],
            doc_date="2026-10-05",
            notes="RA bill 1: foundation and ground floor slab",
            lines=[line("RCC M25 concrete", "42.500"), line("TMT steel Fe500D", "3.200")],
        )
    )
    inv2 = issue(
        draft(
            party_id=skyline["id"],
            project_id=tower["id"],
            doc_date="2026-10-25",
            notes="RA bill 2: ground floor walls",
            lines=[
                line("Brick masonry in CM 1:6", measurements=walls),
                line("Plastering 12 mm, CM 1:4", "480.000"),
            ],
        )
    )
    inv3 = issue(
        draft(
            party_id=green["id"],
            project_id=villas["id"],
            doc_date="2026-10-15",
            lines=[
                line("Vitrified tile flooring 600x600", "850.000"),
                line("Interior painting, two coats", "1200.000"),
            ],
        )
    )
    net1 = inv1["totals"]["net_receivable"]
    api.call(
        "POST",
        "/payments",
        {
            "party_id": skyline["id"],
            "project_id": tower["id"],
            "payment_date": "2026-10-20",
            "amount": net1,
            "mode": "BANK_TRANSFER",
            "reference": "UTR SBIN0026102000451",
            "allocations": [{"document_id": inv1["id"], "amount": net1}],
        },
    )
    api.call(
        "POST",
        "/payments",
        {
            "party_id": skyline["id"],
            "project_id": tower["id"],
            "payment_date": "2026-11-02",
            "amount": "200000.00",
            "mode": "UPI",
            "reference": "UPI 630512345678",
            "allocations": [{"document_id": inv2["id"], "amount": "200000.00"}],
        },
    )
    issue(
        api.call(
            "POST",
            f"/documents/{inv3['id']}/credit-notes",
            {
                "doc_date": "2026-10-28",
                "lines": [
                    line(
                        "Vitrified tile flooring 600x600",
                        "40.000",
                        description="Tiles returned: 40 sqm",
                    )
                ],
            },
        )
    )
    quote = issue(
        draft(
            doc_type="QUOTATION",
            party_id=anil["id"],
            project_id=house["id"],
            doc_date="2026-10-28",
            valid_until="2026-11-27",
            lines=[
                line("Vitrified tile flooring 600x600", "120.000"),
                line("Interior painting, two coats", "450.000"),
                line("Plastering 12 mm, CM 1:4", "60.000"),
            ],
        )
    )
    quote = api.call("POST", f"/documents/{quote['id']}/accept", {}, match=quote["version"])
    api.call(
        "POST", f"/documents/{quote['id']}/convert", {"to": "TAX_INVOICE", "doc_date": "2026-11-04"}
    )
    draft(
        party_id=lakshmi["id"],
        doc_date="2026-11-04",
        lines=[
            line("Cement OPC 53 grade", "200.000", rate="250.00"),
            line("Plastering 12 mm, CM 1:4", "150.000"),
        ],
    )
    # A subcontract work order with its first RA bill (payables part 2).
    ravi = party(
        display_name="Ravi Kumar (brickwork)",
        is_customer=False,
        is_vendor=True,
        gst_treatment="UNREGISTERED",
        pan="ABCPK1234L",
        state_code="32",
    )
    wo = api.call(
        "POST",
        "/work-orders",
        {
            "project_id": house["id"],
            "vendor_party_id": ravi["id"],
            "wo_date": "2026-10-21",
            "title": "Brickwork and plastering",
            "terms": "Cement and steel by us; payment within 15 days of a certified bill.",
            "retention_pct": "5",
            "tds_section": "194C",
            "tds_rate": "1",
            "items": [
                {
                    "item_code": "1",
                    "description": "Brickwork in CM 1:6, ground and first floor",
                    "unit": "cum",
                    "qty": "100",
                    "rate": "4000",
                },
                {
                    "item_code": "2",
                    "description": "Internal plastering 12 mm in CM 1:4",
                    "unit": "sqm",
                    "qty": "500",
                    "rate": "300",
                },
            ],
        },
    )
    api.call(
        "POST",
        f"/work-orders/{wo['id']}/ra-bills",
        {
            "bill_number": "RK/RA-1",
            "bill_date": "2026-11-04",
            "due_date": "2026-11-19",
            "lines": [
                {"work_order_item_id": wo["items"][0]["id"], "qty": "40"},
                {"work_order_item_id": wo["items"][1]["id"], "qty": "200"},
            ],
        },
    )
    print("Added: GSTIN, number series, 4 clients, 3 projects, 7 items, bill printing with a logo,")
    print("INV/0001 (paid), INV/0002 (part paid), INV/0003 with CN/0001, QT/0001 (accepted,")
    print("draft invoice made from it), a draft for Lakshmi Traders with review warnings, and")
    print("work order WO/ANIL-HOUSE/01 for a brickwork subcontractor with its first RA bill.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", ""))
    parser.add_argument("--totp-secret", default=os.environ.get("DEMO_TOTP_SECRET", ""))
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--mailpit", default="http://127.0.0.1:8025")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Password: ")
    api = Api(args.api)
    secret = args.totp_secret
    try:
        sign_in(api, args.email, password, secret)
    except SystemExit as exc:
        if "invalid_credentials" not in str(exc):
            raise
        secret = sign_up(api, args.mailpit, args.email, password)
        sign_in(api, args.email, password, secret)
    seed(api)


if __name__ == "__main__":
    main()
