"""Measurement sheets on bill lines (B.9): quantity from nos x L x B x H rows."""

from typing import Any

import pytest
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.documents.models import Document, DocumentLineMeasurement
from apps.documents.pdf.render import render_html
from tests.documents.test_drafts import RCC
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db

# Plastering a wall: 2 walls of 10.5 m x 3.2 m, less a window of 2.5 m x 3 m.
ROWS = [
    {"description": "Wall A and B", "nos": "2", "length": "10.5", "breadth": "3.2"},
    {"description": "Window", "length": "2.5", "breadth": "3", "deduct": True},
]


@pytest.fixture
def m() -> Money:
    return Money()


def line(r: Any) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.content
    return dict(r.json()["lines"][0])


def test_the_quantity_is_the_total_of_the_rows(m: Money) -> None:
    ln = line(m.create(lines=[{**RCC, "quantity": "999", "measurements": ROWS}]))
    assert ln["quantity"] == "59.700"  # 2 x 10.5 x 3.2 = 67.2, less 7.5 (sent 999: ignored)
    assert ln["taxable_value"] == "405960.00"  # 59.7 x 6800
    assert [(r["row_no"], r["quantity"], r["deduct"]) for r in ln["measurements"]] == [
        (1, "67.200", False),
        (2, "7.500", True),
    ]
    assert ln["measurements"][1]["nos"] == "1.000"  # empty nos: 1
    assert ln["measurements"][1]["height"] is None


def test_rows_round_half_up_to_three_decimals(m: Money) -> None:
    rows = [{"length": "2.125", "breadth": "1.333"}]
    ln = line(m.create(lines=[{**RCC, "measurements": rows}]))
    assert ln["quantity"] == "2.833"  # 2.832625 -> 2.833


def test_measurements_must_add_up_to_more_than_zero(m: Money) -> None:
    rows = [{"length": "2"}, {"length": "2", "deduct": True}]
    r = m.create(lines=[{**RCC, "measurements": rows}])
    assert r.status_code == 422
    assert (r.json()["errors"][0]["field"], r.json()["errors"][0]["code"]) == (
        "lines[0].measurements",
        "measurements_total",
    )


def test_a_line_needs_a_quantity_or_measurements(m: Money) -> None:
    body = {k: v for k, v in RCC.items() if k != "quantity"}
    r = m.create(lines=[body])
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "lines[0].quantity"


def test_rows_are_kept_through_edits_and_replaced_with_the_lines(m: Money) -> None:
    doc = m.create(lines=[{**RCC, "measurements": ROWS}]).json()
    r = APIClient().patch(
        f"/api/v1/documents/{doc['id']}",
        {"notes": "Phase 1"},
        format="json",
        **m.h(IF_MATCH='"v1"'),
    )
    assert len(line(r)["measurements"]) == 2  # a header change keeps them
    r = APIClient().patch(
        f"/api/v1/documents/{doc['id']}",
        {"lines": [{**RCC, "quantity": "5"}]},
        format="json",
        **m.h(IF_MATCH='"v2"'),
    )
    assert line(r)["measurements"] == []
    with tenant_context(m.t.tenant_id, m.t.user_id):
        assert DocumentLineMeasurement.objects.count() == 0  # went with the old lines


def test_issued_bills_keep_their_measurements_frozen(m: Money) -> None:
    bill = m.invoice(lines=[{**RCC, "measurements": ROWS}])
    with tenant_context(m.t.tenant_id, m.t.user_id):
        row = DocumentLineMeasurement.objects.filter(document_id=bill["id"]).first()
        assert row is not None
        with pytest.raises(DatabaseError), transaction.atomic():
            DocumentLineMeasurement.objects.filter(pk=row.pk).update(nos=5)
        with pytest.raises(DatabaseError), transaction.atomic():
            DocumentLineMeasurement.objects.filter(pk=row.pk).delete()


def test_the_pdf_prints_the_rows_under_the_line(m: Money) -> None:
    bill = m.invoice(lines=[{**RCC, "measurements": ROWS}])
    with tenant_context(m.t.tenant_id, m.t.user_id):
        html = render_html(Document.objects.get(pk=bill["id"]))
    assert "Wall A and B 2 × 10.5 × 3.2" in html
    assert "less 7.5" in html
