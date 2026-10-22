"""GST tax engine for billing documents (docs/01-architecture.md §5.4).

Pure Python, no Django: plain data in, plain data out, so it can be tested
exhaustively and reused anywhere (API, preview-totals, imports, PDF).

Rules
* Every amount is Decimal, quantized to paise with ROUND_HALF_UP (Python's
  default is banker's rounding, which does not match GST practice).
* Per line: taxable = round(qty x rate, 2) - discount. Intra-state supplies
  get CGST and SGST at half the rate each, rounded separately (so they are
  always equal); inter-state supplies get IGST at the full rate.
* Place of supply for construction is the site's state (immovable property,
  IGST Act s.12(3)); the caller passes it in.
* Supplies to SEZ units / developers are inter-State whatever the place
  (IGST Act s.7(5)(b)); exports have place of supply 96 (outside India). Both
  are zero-rated (IGST Act s.16): IGST is charged, or nothing under a Letter
  of Undertaking (`lut`), the rates staying on the lines for the return.
* Reverse charge: the recipient pays the tax. It is computed and shown, but
  not part of the document total (nor of what the client pays).
* BILL_OF_SUPPLY, and any document of a non-REGULAR supplier, carries no tax.
  A non-REGULAR supplier cannot issue tax invoices / credit / debit notes.
* GST rates are data (0-50 %), never constants here.
* Deductions after tax reduce what the client pays now, not the taxable
  value: retention (% of taxable), income-tax TDS s.194C (% of the value
  excluding GST, CBDT Circular 23/2017, rounded to the rupee per s.288B),
  GST TDS s.51 (2 % of taxable when applicable), and recovery of the
  mobilisation advance (% of taxable, capped at the advance outstanding).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
MAX_GST_RATE = Decimal("50")
GST_TDS_RATE = Decimal("2")  # CGST Act s.51: 1 % CGST + 1 % SGST, or 2 % IGST

GST_DOC_TYPES = frozenset({"TAX_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"})
DOC_TYPES = frozenset({*GST_DOC_TYPES, "QUOTATION", "PROFORMA", "BILL_OF_SUPPLY"})
REGISTRATION_TYPES = frozenset({"REGULAR", "COMPOSITION", "UNREGISTERED"})
SUPPLY_CATEGORIES = frozenset({"REGULAR", "SEZ", "EXPORT"})
ZERO_RATED = frozenset({"SEZ", "EXPORT"})


class TaxError(ValueError):
    """Input the engine refuses. `field` names the offending input."""

    def __init__(self, field: str, message: str, code: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


def paise(amount: Decimal) -> Decimal:
    return amount.quantize(PAISE, rounding=ROUND_HALF_UP)


def rupees(amount: Decimal) -> Decimal:
    return amount.quantize(RUPEE, rounding=ROUND_HALF_UP).quantize(PAISE)


def percent_of(base: Decimal, pct: Decimal) -> Decimal:
    return paise(base * pct / HUNDRED)


# --- input ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineIn:
    quantity: Decimal  # up to 3 decimals, > 0
    rate: Decimal  # up to 2 decimals, >= 0
    gst_rate: Decimal = ZERO  # percent, 0..50
    discount: Decimal = ZERO  # absolute amount, <= qty x rate
    cess_rate: Decimal = ZERO  # percent of taxable


@dataclass(frozen=True)
class Deductions:
    retention_pct: Decimal = ZERO
    income_tax_tds_pct: Decimal = ZERO
    gst_tds_applicable: bool = False
    advance_recovery_pct: Decimal = ZERO
    advance_outstanding: Decimal = ZERO  # mobilisation advance not yet recovered


@dataclass(frozen=True)
class DocumentIn:
    doc_type: str
    registration_type: str  # supplier's: REGULAR / COMPOSITION / UNREGISTERED
    supplier_state: str  # state code of the issuing registration
    place_of_supply: str  # site state for construction works
    lines: Sequence[LineIn]
    round_to_rupee: bool = False
    deductions: Deductions = field(default_factory=Deductions)
    supply_category: str = "REGULAR"  # REGULAR / SEZ / EXPORT
    lut: bool = False  # zero-rated without payment of IGST (Letter of Undertaking)
    reverse_charge: bool = False  # the recipient pays the tax


# --- output --------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineOut:
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class DocumentOut:
    supply_type: str  # INTRA_STATE / INTER_STATE
    lines: list[LineOut]
    subtotal: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    round_off: Decimal
    grand_total: Decimal
    retention_amount: Decimal
    income_tax_tds_amount: Decimal
    gst_tds_amount: Decimal
    advance_recovery_amount: Decimal
    net_receivable: Decimal


# --- calculation -------------------------------------------------------------------------


def _decimals(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _check_line(i: int, line: LineIn) -> None:
    where = f"lines[{i}]"
    if line.quantity <= 0 or _decimals(line.quantity) > 3:
        raise TaxError(
            f"{where}.quantity", "Quantity must be > 0 with at most 3 decimals.", "invalid"
        )
    if line.rate < 0 or _decimals(line.rate) > 2:
        raise TaxError(f"{where}.rate", "Rate must be >= 0 with at most 2 decimals.", "invalid")
    if not ZERO <= line.gst_rate <= MAX_GST_RATE or _decimals(line.gst_rate) > 2:
        raise TaxError(f"{where}.gst_rate", "GST rate must be 0 to 50 %.", "invalid")
    if not ZERO <= line.cess_rate <= HUNDRED or _decimals(line.cess_rate) > 2:
        raise TaxError(f"{where}.cess_rate", "Cess rate must be 0 to 100 %.", "invalid")
    if line.discount < 0 or _decimals(line.discount) > 2:
        raise TaxError(f"{where}.discount", "Discount must be >= 0 rupees and paise.", "invalid")


def _check_percent(name: str, value: Decimal) -> None:
    if not ZERO <= value <= HUNDRED:
        raise TaxError(f"deductions.{name}", "Must be 0 to 100 %.", "invalid")


def compute_line(line: LineIn, *, taxed: bool, intra_state: bool) -> LineOut:
    gross = paise(line.quantity * line.rate)
    if line.discount > gross:
        raise TaxError("discount", "Discount exceeds the line amount.", "discount_too_large")
    taxable = gross - line.discount
    cgst = sgst = igst = cess = ZERO
    if taxed:
        if intra_state:
            cgst = sgst = percent_of(taxable, line.gst_rate / 2)
        else:
            igst = percent_of(taxable, line.gst_rate)
        cess = percent_of(taxable, line.cess_rate)
    return LineOut(
        taxable_value=taxable,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        cess_amount=cess,
        line_total=taxable + cgst + sgst + igst + cess,
    )


def _check_category(doc: DocumentIn, taxed: bool) -> None:
    if doc.supply_category not in SUPPLY_CATEGORIES:
        raise TaxError("supply_category", "Unknown supply category.", "invalid")
    if doc.supply_category == "EXPORT" and doc.place_of_supply != "96":
        raise TaxError("place_of_supply", "Exports have place of supply 96.", "invalid")
    if doc.lut and doc.supply_category not in ZERO_RATED:
        raise TaxError(
            "lut",
            "Only supplies to SEZ units and exports go under a Letter of Undertaking.",
            "lut_not_zero_rated",
        )
    if doc.lut and not taxed:
        raise TaxError("lut", "This document carries no tax.", "lut_not_zero_rated")
    if doc.reverse_charge and (doc.supply_category in ZERO_RATED or not taxed):
        raise TaxError(
            "reverse_charge",
            "Only tax invoices and notes of a regular registration, to clients in India"
            " outside SEZs, can be under reverse charge.",
            "reverse_charge_not_allowed",
        )


def compute(doc: DocumentIn) -> DocumentOut:
    if doc.doc_type not in DOC_TYPES:
        raise TaxError("doc_type", f"Unknown document type {doc.doc_type}.", "invalid")
    if doc.registration_type not in REGISTRATION_TYPES:
        raise TaxError("registration_type", "Unknown registration type.", "invalid")
    if doc.registration_type != "REGULAR" and doc.doc_type in GST_DOC_TYPES:
        raise TaxError(
            "doc_type",
            f"A {doc.registration_type} registration cannot issue {doc.doc_type};"
            " use BILL_OF_SUPPLY.",
            "doc_type_not_allowed",
        )
    if not doc.lines:
        raise TaxError("lines", "A document needs at least one line.", "no_lines")

    taxed = doc.registration_type == "REGULAR" and doc.doc_type != "BILL_OF_SUPPLY"
    _check_category(doc, taxed)
    zero_rated = doc.supply_category in ZERO_RATED
    intra_state = not zero_rated and doc.place_of_supply == doc.supplier_state
    pays_tax = taxed and not doc.lut

    lines: list[LineOut] = []
    for i, line in enumerate(doc.lines):
        _check_line(i, line)
        try:
            lines.append(compute_line(line, taxed=pays_tax, intra_state=intra_state))
        except TaxError as exc:
            raise TaxError(f"lines[{i}].{exc.field}", str(exc), exc.code) from None

    subtotal = sum((ln.taxable_value for ln in lines), ZERO)
    cgst = sum((ln.cgst_amount for ln in lines), ZERO)
    sgst = sum((ln.sgst_amount for ln in lines), ZERO)
    igst = sum((ln.igst_amount for ln in lines), ZERO)
    cess = sum((ln.cess_amount for ln in lines), ZERO)
    # Under reverse charge the recipient pays the tax to the government.
    charged = ZERO if doc.reverse_charge else cgst + sgst + igst + cess
    before_rounding = subtotal + charged
    grand_total = rupees(before_rounding) if doc.round_to_rupee else before_rounding
    round_off = grand_total - before_rounding

    d = doc.deductions
    for name in ("retention_pct", "income_tax_tds_pct", "advance_recovery_pct"):
        _check_percent(name, getattr(d, name))
    if d.advance_outstanding < 0:
        raise TaxError("deductions.advance_outstanding", "Must be >= 0.", "invalid")
    retention = percent_of(subtotal, d.retention_pct)
    income_tax_tds = rupees(subtotal * d.income_tax_tds_pct / HUNDRED)
    gst_tds = percent_of(subtotal, GST_TDS_RATE) if d.gst_tds_applicable and pays_tax else ZERO
    advance = min(percent_of(subtotal, d.advance_recovery_pct), paise(d.advance_outstanding))
    net = grand_total - retention - income_tax_tds - gst_tds - advance
    if net < 0:
        raise TaxError(
            "deductions", "Deductions exceed the document total.", "deductions_exceed_total"
        )

    return DocumentOut(
        supply_type="INTRA_STATE" if intra_state else "INTER_STATE",
        lines=lines,
        subtotal=subtotal,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        cess_amount=cess,
        round_off=round_off,
        grand_total=grand_total,
        retention_amount=retention,
        income_tax_tds_amount=income_tax_tds,
        gst_tds_amount=gst_tds,
        advance_recovery_amount=advance,
        net_receivable=net,
    )
