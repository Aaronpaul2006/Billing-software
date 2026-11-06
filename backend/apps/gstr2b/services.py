"""Uploading a GSTR-2B (Part B): the file is read, checked to be for one of
our registrations, and replaces any upload of the same month."""

from django.db import transaction

from apps.core.errors import Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.tenants.models import GstRegistration

from . import reader
from .models import Gstr2bLine, Gstr2bReturn

UPLOAD = "payments.record"


def upload(principal: Principal, data: bytes, file_name: str) -> Gstr2bReturn:
    require(principal, UPLOAD)
    parsed = reader.read(data)
    registration = GstRegistration.objects.filter(gstin=parsed.gstin).first()
    if registration is None:
        raise Invalid(
            "file",
            f"This GSTR-2B is for GSTIN {parsed.gstin or '(none)'}, which is not one of your "
            "GST registrations.",
            code="other_gstin",
        )
    with transaction.atomic():
        old = Gstr2bReturn.objects.filter(
            gst_registration=registration, period=parsed.period
        ).first()
        if old is not None:  # the month uploaded again: the new file replaces it
            Gstr2bLine.objects.filter(gst_return=old).delete()
            old.delete()
        gst_return = Gstr2bReturn(
            gst_registration=registration,
            period=parsed.period,
            generated_on=parsed.generated_on,
            file_name=(file_name or "gstr2b.json")[:255],
            doc_count=len(parsed.docs),
            created_by_id=principal.user_id,
        )
        gst_return.save()
        Gstr2bLine.objects.bulk_create(
            [
                Gstr2bLine(
                    tenant_id=principal.tenant_id,  # bulk_create skips save(): set it here
                    gst_return=gst_return,
                    section=d.section,
                    doc_type=d.doc_type,
                    supplier_gstin=d.supplier_gstin,
                    supplier_name=d.supplier_name,
                    doc_number=d.number[:50],
                    original_number=d.original_number or None,
                    doc_date=d.doc_date,
                    taxable_value=d.taxable_value,
                    igst=d.igst,
                    cgst=d.cgst,
                    sgst=d.sgst,
                    cess=d.cess,
                    place_of_supply=d.place_of_supply or None,
                    reverse_charge=d.reverse_charge,
                    itc_available=d.itc_available,
                    itc_reason=d.itc_reason or None,
                )
                for d in parsed.docs
            ],
            batch_size=1000,
        )
    return get_or_404(Gstr2bReturn, gst_return.pk)
