"""Discount as a percentage, and due dates from the client's payment terms (B.5)."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.documents.test_drafts import RCC, World

pytestmark = pytest.mark.django_db


@pytest.fixture
def w() -> World:
    return World()


def line(r: Any) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.content
    return dict(r.json()["lines"][0])


def test_a_percentage_discount_is_worked_out_to_the_paisa(w: World) -> None:
    # 42.5 cum x 6800 = 289000.00; 10 % = 28900.00
    ln = line(w.create(lines=[{**RCC, "discount_pct": "10"}]))
    assert (ln["discount_pct"], ln["discount_amount"], ln["taxable_value"]) == (
        "10.00",
        "28900.00",
        "260100.00",
    )
    # 3 x 33.33 = 99.99; 12.5 % = 12.49875 -> 12.50 (half up)
    odd = line(w.create(lines=[{**RCC, "quantity": "3", "rate": "33.33", "discount_pct": "12.5"}]))
    assert (odd["discount_amount"], odd["taxable_value"]) == ("12.50", "87.49")


def test_the_percentage_wins_over_an_amount_sent_with_it(w: World) -> None:
    ln = line(w.create(lines=[{**RCC, "discount_pct": "10", "discount_amount": "5"}]))
    assert ln["discount_amount"] == "28900.00"


def test_an_amount_alone_still_works_and_has_no_percentage(w: World) -> None:
    ln = line(w.create(lines=[{**RCC, "discount_amount": "1000"}]))
    assert (ln["discount_pct"], ln["discount_amount"]) == (None, "1000.00")


def test_the_percentage_is_kept_and_recomputed_when_the_draft_changes(w: World) -> None:
    created = w.create(lines=[{**RCC, "discount_pct": "10"}]).json()
    # a header change re-sends the stored lines: the % stays
    r = APIClient().patch(
        f"/api/v1/documents/{created['id']}",
        {"notes": "Phase 1"},
        format="json",
        **w.h(IF_MATCH='"v1"'),
    )
    assert line(r)["discount_pct"] == "10.00"
    # a new quantity: the same % of the new value
    r = APIClient().patch(
        f"/api/v1/documents/{created['id']}",
        {"lines": [{**RCC, "quantity": "10", "discount_pct": "10"}]},
        format="json",
        **w.h(IF_MATCH='"v2"'),
    )
    assert line(r)["discount_amount"] == "6800.00"


def test_more_than_100_percent_is_refused(w: World) -> None:
    r = w.create(lines=[{**RCC, "discount_pct": "100.01"}])
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "lines[0].discount_pct"


def test_a_new_bill_falls_due_by_the_clients_payment_terms(w: World) -> None:
    r = APIClient().patch(
        f"/api/v1/parties/{w.client.pk}",
        {"payment_terms_days": 30},
        format="json",
        **w.h(IF_MATCH=f'"v{w.client.version}"'),
    )
    assert r.status_code == 200, r.content
    assert r.json()["payment_terms_days"] == 30

    bill = w.create(doc_date="2026-10-19").json()
    assert bill["due_date"] == "2026-11-18"
    typed = w.create(doc_date="2026-10-19", due_date="2026-10-25").json()
    assert typed["due_date"] == "2026-10-25"  # a typed due date is kept
    quote = w.create(doc_type="QUOTATION", doc_date="2026-10-19").json()
    assert quote["due_date"] is None  # quotations do not fall due


def test_payment_terms_are_0_to_365_days(w: World) -> None:
    r = APIClient().patch(
        f"/api/v1/parties/{w.client.pk}",
        {"payment_terms_days": 400},
        format="json",
        **w.h(IF_MATCH=f'"v{w.client.version}"'),
    )
    assert r.status_code == 422
    with tenant_context(w.t.tenant_id, w.t.user_id):
        assert Party.objects.get(pk=w.client.pk).payment_terms_days is None
