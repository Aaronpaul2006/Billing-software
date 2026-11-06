"""A sample business to explore with (Part B).

A separate business (tenant), owned by the person who asked, marked
is_sample: its bills, numbers and returns can never touch the real
business, as every row belongs to one tenant (row-level security). It is
filled through the same services as the screens, so everything in it passes
the same checks. Removing it closes it: it leaves the business switcher.

Made by a background task after the request that asked for it, because one
transaction never works in two businesses (apps/core/tenancy.py).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, Role
from apps.core.india import fy_start_year, gstin_check_char
from apps.core.tenancy import Principal, tenant_context, user_context

from .models import DocumentSeries, GstRegistration, Tenant

NAME = "Sample: Green Valley Builders"


def _gstin(state: str, pan: str) -> str:
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


def existing(user_id: uuid.UUID) -> Tenant | None:
    """The user's open sample business, if any."""
    with user_context(user_id):
        ids = Membership.objects.filter(user_id=user_id, status="ACTIVE", role=Role.OWNER)
        return (
            Tenant.objects.filter(id__in=ids.values("tenant_id"), is_sample=True, status="ACTIVE")
            .order_by("-created_at")
            .first()
        )


def _validated(serializer: Any, data: dict[str, Any]) -> dict[str, Any]:
    s = serializer(data=data)
    s.is_valid(raise_exception=True)
    return dict(s.validated_data)


def build(user_id: uuid.UUID, today: date | None = None) -> uuid.UUID:
    """Make the sample business and fill it; returns its id."""
    from apps.diary.models import DiaryEntry
    from apps.documents.serializers import DocumentWriteSerializer
    from apps.documents.services import drafts, lifecycle
    from apps.parties.models import Party
    from apps.payables import services as payables
    from apps.payables.serializers import VendorBillWriteSerializer
    from apps.payments import services as payments
    from apps.payments.serializers import PaymentCreateSerializer
    from apps.projects.models import BoqItem, Project

    found = existing(user_id)
    if found is not None:
        return found.pk
    today = today or timezone.localdate()
    tenant_id = uuid.uuid7()
    principal = Principal(user_id=user_id, tenant_id=tenant_id, role=Role.OWNER)

    def day(n: int) -> str:
        return (today - timedelta(days=n)).isoformat()

    with transaction.atomic(), tenant_context(tenant_id, user_id):
        Tenant.objects.create(id=tenant_id, legal_name=NAME, is_sample=True)
        Membership.objects.create(tenant_id=tenant_id, user_id=user_id, role=Role.OWNER)
        address = {"line1": "12 MG Road", "city": "Kochi", "state_code": "32", "pincode": "682016"}
        registration = GstRegistration.objects.create(
            registration_type="REGULAR",
            gstin=_gstin("32", "AAGFG1234K"),
            state_code="32",
            legal_name="Green Valley Builders",
            address=address,
            is_default=True,
        )
        for fy in sorted({fy_start_year(today), fy_start_year(today - timedelta(days=60))}):
            for doc_type, prefix in (("TAX_INVOICE", "INV/"), ("QUOTATION", "QT/")):
                DocumentSeries.objects.create(
                    gst_registration=registration,
                    doc_type=doc_type,
                    fy_start_year=fy,
                    prefix=prefix,
                )
        client = Party.objects.create(
            display_name="Riverside Apartments",
            legal_name="Riverside Apartments Pvt Ltd",
            gst_treatment="REGISTERED",
            gstin=_gstin("32", "AABCR4321K"),
            pan="AABCR4321K",
            state_code="32",
            email="accounts@riverside.example",
            created_by_id=user_id,
        )
        home = Party.objects.create(
            display_name="Meera Nair",
            gst_treatment="CONSUMER",
            state_code="32",
            created_by_id=user_id,
        )
        vendor = Party.objects.create(
            display_name="Coastal Cement",
            gst_treatment="REGISTERED",
            gstin=_gstin("32", "AAACC5678P"),
            pan="AAACC5678P",
            state_code="32",
            is_customer=False,
            is_vendor=True,
            created_by_id=user_id,
        )
        project = Project.objects.create(
            code="RIVERSIDE",
            name="Riverside Apartments, Block A",
            client_party=client,
            gst_registration_id=registration.pk,
            site_state_code="32",
            contract_value=Decimal("4500000"),
            retention_pct=Decimal("5"),
            income_tax_tds_pct=Decimal("1"),
            created_by_id=user_id,
        )
        boq = [
            BoqItem.objects.create(
                project=project,
                item_code=code,
                description=what,
                unit=unit,
                contract_qty=Decimal(qty),
                rate=Decimal(rate),
                gst_rate=Decimal("18"),
                sac_hsn="995453",
                sort_order=i,
            )
            for i, (code, what, unit, qty, rate) in enumerate(
                (
                    ("1.1", "Excavation in foundations", "cum", "400", "450"),
                    ("2.1", "RCC M25 in columns and slabs", "cum", "180", "6800"),
                    ("3.1", "Brickwork in CM 1:6", "cum", "220", "5200"),
                )
            )
        ]

        def bill(**data: Any) -> Any:
            doc = drafts.create_draft(principal, _validated(DocumentWriteSerializer, data))
            return lifecycle.issue(principal, doc.pk, doc.version, check_email=False)

        ra1 = bill(
            doc_type="TAX_INVOICE",
            party_id=client.pk,
            project_id=project.pk,
            doc_date=day(40),
            is_ra_bill=True,
            lines=[
                {"boq_item_id": boq[0].pk, "quantity": "400"},
                {"boq_item_id": boq[1].pk, "quantity": "40"},
            ],
        )
        bill(
            doc_type="TAX_INVOICE",
            party_id=client.pk,
            project_id=project.pk,
            doc_date=day(10),
            is_ra_bill=True,
            lines=[
                {"boq_item_id": boq[1].pk, "quantity": "35"},
                {"boq_item_id": boq[2].pk, "quantity": "60"},
            ],
        )
        bill(
            doc_type="QUOTATION",
            party_id=home.pk,
            doc_date=day(5),
            valid_until=(today + timedelta(days=25)).isoformat(),
            lines=[
                {
                    "description": "Kitchen renovation, complete",
                    "unit": "job",
                    "quantity": "1",
                    "rate": "285000",
                    "gst_rate": "18",
                    "sac_hsn": "995454",
                }
            ],
        )
        payments.record_payment(
            principal,
            _validated(
                PaymentCreateSerializer,
                {
                    "party_id": client.pk,
                    "project_id": project.pk,
                    "payment_date": day(25),
                    "amount": str(ra1.net_receivable),
                    "mode": "BANK_TRANSFER",
                    "reference": "UTR SBIN0000000001",
                    "allocations": [{"document_id": ra1.pk, "amount": str(ra1.net_receivable)}],
                },
            ),
        )
        payables.record_bill(
            principal,
            _validated(
                VendorBillWriteSerializer,
                {
                    "vendor_party_id": vendor.pk,
                    "project_id": project.pk,
                    "bill_number": "CC/2201",
                    "bill_date": day(12),
                    "due_date": day(-3),
                    "category": "MATERIAL",
                    "description": "Cement OPC 53, 600 bags",
                    "taxable_value": "222000.00",
                    "gst_amount": "39960.00",
                    "itc_eligible": True,
                },
            ),
        )
        for n, weather, workers, work in (
            (2, "SUNNY", 18, "Brickwork on the second floor, grids A to D."),
            (
                1,
                "CLOUDY",
                16,
                "Second floor brickwork finished; scaffolding moved to the east side.",
            ),
        ):
            DiaryEntry.objects.create(
                project=project,
                entry_date=today - timedelta(days=n),
                weather=weather,
                workers=workers,
                work_done=work,
                created_by_id=user_id,
            )
    return tenant_id


def close(principal: Principal) -> None:
    """Remove (close) the sample business the person is in."""
    from apps.core.errors import Conflict, Forbidden

    tenant = Tenant.objects.get(pk=principal.tenant_id)
    if not tenant.is_sample:
        raise Conflict("This is not a sample business.", code="not_a_sample")
    if principal.role != Role.OWNER:
        raise Forbidden("Only its owner removes the sample business.", code="owner_only")
    Tenant.objects.filter(pk=tenant.pk).update(status="CLOSED", updated_at=timezone.now())
