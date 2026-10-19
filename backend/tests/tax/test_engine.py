"""Tax engine: worked examples (table-driven) and properties (Hypothesis)."""

import ast
from decimal import Decimal as D
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.documents.tax import Deductions, DocumentIn, LineIn, TaxError, compute
from apps.documents.tax.engine import paise, rupees

KERALA, KARNATAKA = "32", "29"


def doc(*lines: LineIn, **kw: object) -> DocumentIn:
    base: dict[str, object] = {
        "doc_type": "TAX_INVOICE",
        "registration_type": "REGULAR",
        "supplier_state": KERALA,
        "place_of_supply": KERALA,
        "lines": list(lines),
    }
    return DocumentIn(**{**base, **kw})  # type: ignore[arg-type]


# --- worked examples ---------------------------------------------------------------


def test_api_design_example_ra_bill() -> None:
    """docs/02-api-design.md §5: 42.500 cum RCC at ₹6800, 18 %, 5 % retention,
    1 % TDS → net receivable ₹3,23,680.00."""
    out = compute(
        doc(
            LineIn(quantity=D("42.500"), rate=D("6800.00"), gst_rate=D("18.00")),
            deductions=Deductions(retention_pct=D("5"), income_tax_tds_pct=D("1")),
        )
    )
    assert out.supply_type == "INTRA_STATE"
    assert (out.subtotal, out.cgst_amount, out.sgst_amount, out.igst_amount) == (
        D("289000.00"),
        D("26010.00"),
        D("26010.00"),
        D("0.00"),
    )
    assert out.grand_total == D("341020.00")
    assert (out.retention_amount, out.income_tax_tds_amount) == (D("14450.00"), D("2890.00"))
    assert out.net_receivable == D("323680.00")


def test_inter_state_site_gets_igst() -> None:
    """Supplier registered in Kerala, site in Karnataka: place of supply is the site."""
    out = compute(
        doc(LineIn(quantity=D("10"), rate=D("1000"), gst_rate=D("18")), place_of_supply=KARNATAKA)
    )
    assert out.supply_type == "INTER_STATE"
    assert (out.cgst_amount, out.sgst_amount, out.igst_amount) == (
        D("0.00"),
        D("0.00"),
        D("1800.00"),
    )
    assert out.grand_total == D("11800.00")


@pytest.mark.parametrize(
    ("line", "intra", "expected"),
    [
        # 0.25 × 18 % = 0.045: half-up gives 0.05 (banker's rounding would give 0.04)
        (
            LineIn(quantity=D("1"), rate=D("0.25"), gst_rate=D("18")),
            False,
            {"igst_amount": D("0.05")},
        ),
        # qty × rate = 0.125 → taxable 0.13 (banker's: 0.12)
        (LineIn(quantity=D("0.125"), rate=D("1.00")), False, {"taxable_value": D("0.13")}),
        # each half rate rounded separately: 10.05 × 9 % = 0.9045 → 0.90 + 0.90
        (
            LineIn(quantity=D("1"), rate=D("10.05"), gst_rate=D("18")),
            True,
            {"cgst_amount": D("0.90"), "sgst_amount": D("0.90"), "line_total": D("11.85")},
        ),
        # 2.5 % CGST + 2.5 % SGST on 5 % goods: 333.33 × 2.5 % = 8.33325 → 8.33
        (
            LineIn(quantity=D("1"), rate=D("333.33"), gst_rate=D("5")),
            True,
            {"cgst_amount": D("8.33"), "sgst_amount": D("8.33")},
        ),
        # discount comes off before tax
        (
            LineIn(quantity=D("2"), rate=D("500"), gst_rate=D("12"), discount=D("100")),
            False,
            {"taxable_value": D("900.00"), "igst_amount": D("108.00")},
        ),
        # cess on taxable value
        (
            LineIn(quantity=D("1"), rate=D("1000"), gst_rate=D("28"), cess_rate=D("12")),
            False,
            {"igst_amount": D("280.00"), "cess_amount": D("120.00"), "line_total": D("1400.00")},
        ),
    ],
)
def test_line_rounding(line: LineIn, intra: bool, expected: dict[str, D]) -> None:
    out = compute(doc(line, place_of_supply=KERALA if intra else KARNATAKA)).lines[0]
    for name, value in expected.items():
        assert getattr(out, name) == value, name


def test_round_off_to_the_nearest_rupee() -> None:
    # intra-state: 100.40 × 9 % = 9.036 → 9.04 CGST + 9.04 SGST → 118.48 → ₹118
    line = LineIn(quantity=D("1"), rate=D("100.40"), gst_rate=D("18"))
    out = compute(doc(line, round_to_rupee=True))
    assert (out.grand_total, out.round_off) == (D("118.00"), D("-0.48"))
    # 100.50 × 9 % = 9.045 → 9.05 + 9.05 → 118.60 → ₹119
    up = compute(
        doc(LineIn(quantity=D("1"), rate=D("100.50"), gst_rate=D("18")), round_to_rupee=True)
    )
    assert (up.grand_total, up.round_off) == (D("119.00"), D("0.40"))


def test_bill_of_supply_and_non_regular_suppliers_carry_no_tax() -> None:
    line = LineIn(quantity=D("1"), rate=D("1000"), gst_rate=D("18"))
    for kw in (
        {"doc_type": "BILL_OF_SUPPLY"},
        {"doc_type": "BILL_OF_SUPPLY", "registration_type": "COMPOSITION"},
        {"doc_type": "QUOTATION", "registration_type": "UNREGISTERED"},
    ):
        out = compute(doc(line, **kw))
        assert out.cgst_amount + out.sgst_amount + out.igst_amount + out.cess_amount == 0
        assert out.grand_total == D("1000.00")


def test_composition_supplier_cannot_issue_a_tax_invoice() -> None:
    with pytest.raises(TaxError) as exc_info:
        compute(doc(LineIn(quantity=D("1"), rate=D("1")), registration_type="COMPOSITION"))
    assert exc_info.value.code == "doc_type_not_allowed"


def test_all_deductions() -> None:
    out = compute(
        doc(
            LineIn(quantity=D("1"), rate=D("1000000.00"), gst_rate=D("18")),  # ₹10 lakh works
            deductions=Deductions(
                retention_pct=D("5"),
                income_tax_tds_pct=D("2"),
                gst_tds_applicable=True,
                advance_recovery_pct=D("10"),
                advance_outstanding=D("60000"),
            ),
        )
    )
    assert out.grand_total == D("1180000.00")
    assert out.retention_amount == D("50000.00")  # 5 % of taxable
    assert out.income_tax_tds_amount == D("20000.00")  # 2 % of value excluding GST
    assert out.gst_tds_amount == D("20000.00")  # 2 % of taxable (s.51)
    assert out.advance_recovery_amount == D("60000.00")  # 10 % = 1 lakh, capped at outstanding
    assert out.net_receivable == D("1030000.00")


def test_income_tax_tds_is_rounded_to_the_rupee() -> None:
    out = compute(
        doc(
            LineIn(quantity=D("1"), rate=D("1234.50")),
            deductions=Deductions(income_tax_tds_pct=D("1")),
        )  # 12.345 → ₹12
    )
    assert out.income_tax_tds_amount == D("12.00")


@pytest.mark.parametrize(
    ("kw", "field", "code"),
    [
        ({"lines": []}, "lines", "no_lines"),
        ({"lines": [LineIn(quantity=D("0"), rate=D("1"))]}, "lines[0].quantity", "invalid"),
        ({"lines": [LineIn(quantity=D("1.0001"), rate=D("1"))]}, "lines[0].quantity", "invalid"),
        ({"lines": [LineIn(quantity=D("1"), rate=D("1.001"))]}, "lines[0].rate", "invalid"),
        (
            {"lines": [LineIn(quantity=D("1"), rate=D("1"), gst_rate=D("51"))]},
            "lines[0].gst_rate",
            "invalid",
        ),
        (
            {"lines": [LineIn(quantity=D("1"), rate=D("10"), discount=D("11"))]},
            "lines[0].discount",
            "discount_too_large",
        ),
        ({"deductions": Deductions(retention_pct=D("101"))}, "deductions.retention_pct", "invalid"),
        (
            {"deductions": Deductions(retention_pct=D("100"), income_tax_tds_pct=D("100"))},
            "deductions",
            "deductions_exceed_total",
        ),
    ],
)
def test_invalid_input(kw: dict[str, object], field: str, code: str) -> None:
    base = doc(LineIn(quantity=D("1"), rate=D("100")))
    with pytest.raises(TaxError) as exc_info:
        compute(DocumentIn(**{**base.__dict__, **kw}))
    assert (exc_info.value.field, exc_info.value.code) == (field, code)


def test_rounding_helpers() -> None:
    assert paise(D("2.675")) == D("2.68")  # banker's would give 2.67 (or 2.68 by float luck)
    assert rupees(D("12.50")) == D("13.00")
    assert rupees(D("-0.50")) == D("-1.00")


def test_engine_has_no_django_imports() -> None:
    """The engine must stay pure (docs/01-architecture.md §5.4)."""
    package = Path(__file__).resolve().parents[2] / "apps" / "documents" / "tax"
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(
                n.split(".")[0] in {"django", "rest_framework", "apps"} for n in names
            ), source


# --- properties ------------------------------------------------------------------------

quantities = st.decimals(min_value=D("0.001"), max_value=D("100000"), places=3)
rates = st.decimals(min_value=D("0"), max_value=D("1000000"), places=2)
gst_rates = st.sampled_from([D("0"), D("0.25"), D("3"), D("5"), D("12"), D("18"), D("28"), D("40")])
lines_strategy = st.lists(
    st.builds(LineIn, quantity=quantities, rate=rates, gst_rate=gst_rates), min_size=1, max_size=8
)
states = st.sampled_from([KERALA, KARNATAKA, "27", "33"])


@settings(max_examples=300, deadline=None)
@given(
    lines=lines_strategy,
    place=states,
    round_to_rupee=st.booleans(),
    doc_type=st.sampled_from(
        ["TAX_INVOICE", "QUOTATION", "PROFORMA", "BILL_OF_SUPPLY", "DEBIT_NOTE"]
    ),
)
def test_totals_are_consistent(
    lines: list[LineIn], place: str, round_to_rupee: bool, doc_type: str
) -> None:
    out = compute(
        doc(*lines, place_of_supply=place, round_to_rupee=round_to_rupee, doc_type=doc_type)
    )
    # header totals are the sums of the lines (the issue trigger checks this)
    assert out.subtotal == sum(ln.taxable_value for ln in out.lines)
    assert out.cgst_amount == sum(ln.cgst_amount for ln in out.lines)
    assert out.igst_amount == sum(ln.igst_amount for ln in out.lines)
    # the database CHECK identities
    assert out.cgst_amount == out.sgst_amount
    for ln in out.lines:
        assert ln.cgst_amount == ln.sgst_amount
        assert (
            ln.line_total
            == ln.taxable_value + ln.cgst_amount + ln.sgst_amount + ln.igst_amount + ln.cess_amount
        )
    if out.supply_type == "INTRA_STATE":
        assert out.igst_amount == 0
    else:
        assert out.cgst_amount == out.sgst_amount == 0
    assert out.grand_total == (
        out.subtotal
        + out.cgst_amount
        + out.sgst_amount
        + out.igst_amount
        + out.cess_amount
        + out.round_off
    )
    assert abs(out.round_off) <= D("0.50")
    assert out.net_receivable == out.grand_total  # no deductions here
    # every amount is in paise
    for value in (out.subtotal, out.cgst_amount, out.igst_amount, out.grand_total, out.round_off):
        assert value == value.quantize(D("0.01"))


@settings(max_examples=300, deadline=None)
@given(lines=lines_strategy)
def test_tax_is_within_a_paisa_of_exact_per_line(lines: list[LineIn]) -> None:
    out = compute(doc(*lines, place_of_supply=KARNATAKA))
    for line, ln in zip(lines, out.lines, strict=True):
        exact = ln.taxable_value * line.gst_rate / 100
        assert abs(ln.igst_amount - exact) <= D("0.005")


@settings(max_examples=200, deadline=None)
@given(
    lines=lines_strategy,
    retention=st.decimals(min_value=D("0"), max_value=D("10"), places=2),
    tds=st.decimals(min_value=D("0"), max_value=D("2"), places=2),
    gst_tds=st.booleans(),
    outstanding=st.decimals(min_value=D("0"), max_value=D("10000000"), places=2),
)
def test_deductions_identity(
    lines: list[LineIn], retention: D, tds: D, gst_tds: bool, outstanding: D
) -> None:
    out = compute(
        doc(
            *lines,
            deductions=Deductions(
                retention_pct=retention,
                income_tax_tds_pct=tds,
                gst_tds_applicable=gst_tds,
                advance_recovery_pct=D("10"),
                advance_outstanding=outstanding,
            ),
        )
    )
    assert out.net_receivable == (
        out.grand_total
        - out.retention_amount
        - out.income_tax_tds_amount
        - out.gst_tds_amount
        - out.advance_recovery_amount
    )
    assert out.net_receivable >= 0
    assert out.advance_recovery_amount <= outstanding


def test_rounding_a_tiny_bill_to_zero_cannot_leave_deductions() -> None:
    """Found by Hypothesis: 0.095 x Rs 1 = 0.10 taxable, 0.12 with GST, rounds to
    Rs 0; 5 % retention (0.01) would then exceed the total. Refused, not negative."""
    with pytest.raises(TaxError) as exc_info:
        compute(
            doc(
                LineIn(quantity=D("0.095"), rate=D("1.00"), gst_rate=D("18")),
                round_to_rupee=True,
                deductions=Deductions(retention_pct=D("5")),
            )
        )
    assert exc_info.value.code == "deductions_exceed_total"
