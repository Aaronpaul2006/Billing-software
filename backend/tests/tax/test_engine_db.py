"""Engine output satisfies the database's own rules (CHECKs + issue trigger)."""

import uuid
from decimal import Decimal as D

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.core.tenancy import tenant_context
from apps.documents.tax import Deductions, DocumentIn, LineIn, compute
from tests.db.seed import issue, new_draft, seed_tenant, sql

pytestmark = pytest.mark.django_db

lines_strategy = st.lists(
    st.builds(
        LineIn,
        quantity=st.decimals(min_value=D("0.001"), max_value=D("5000"), places=3),
        rate=st.decimals(min_value=D("0"), max_value=D("100000"), places=2),
        gst_rate=st.sampled_from([D("0"), D("5"), D("12"), D("18"), D("28")]),
    ),
    min_size=1,
    max_size=5,
)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(lines=lines_strategy, place=st.sampled_from(["32", "29"]), round_to_rupee=st.booleans())
def test_computed_documents_pass_the_database_checks(
    lines: list[LineIn], place: str, round_to_rupee: bool
) -> None:
    s = seed_tenant("T", f"32AAACT{uuid.uuid4().int % 10000:04d}T1Z5", "32")  # format only
    out = compute(
        DocumentIn(
            doc_type="TAX_INVOICE",
            registration_type="REGULAR",
            supplier_state="32",
            place_of_supply=place,
            lines=lines,
            round_to_rupee=round_to_rupee,
            deductions=Deductions(retention_pct=D("5"), income_tax_tds_pct=D("1")),
        )
    )
    with tenant_context(s.tenant, s.user):
        doc = new_draft(s, uuid.uuid7(), place=place)
        sql("UPDATE documents SET supply_type = %s WHERE id = %s", [out.supply_type, doc])
        for i, (line, ln) in enumerate(zip(lines, out.lines, strict=True), start=1):
            sql(
                "INSERT INTO document_lines (tenant_id, document_id, line_no, description, quantity,"
                " rate, taxable_value, gst_rate, cgst_amount, sgst_amount, igst_amount,"
                " cess_amount, line_total)"
                " VALUES (%s, %s, %s, 'item', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    s.tenant,
                    doc,
                    i,
                    line.quantity,
                    line.rate,
                    ln.taxable_value,
                    line.gst_rate,
                    ln.cgst_amount,
                    ln.sgst_amount,
                    ln.igst_amount,
                    ln.cess_amount,
                    ln.line_total,
                ],
            )
        sql(
            "UPDATE documents SET subtotal = %s, cgst_amount = %s, sgst_amount = %s,"
            " igst_amount = %s, cess_amount = %s, round_off = %s, grand_total = %s,"
            " retention_amount = %s, income_tax_tds_amount = %s, net_receivable = %s"
            " WHERE id = %s",
            [
                out.subtotal,
                out.cgst_amount,
                out.sgst_amount,
                out.igst_amount,
                out.cess_amount,
                out.round_off,
                out.grand_total,
                out.retention_amount,
                out.income_tax_tds_amount,
                out.net_receivable,
                doc,
            ],
        )
        issue(s, doc)  # the trigger re-verifies totals = Σ lines and supply type
        assert sql("SELECT status FROM documents WHERE id = %s", [doc]) == [("ISSUED",)]
