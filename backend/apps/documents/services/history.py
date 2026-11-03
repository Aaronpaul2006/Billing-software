"""A bill's change history in plain words (B.11).

Read from the audit trail (every change to the bill and its lines, written by
triggers, so it cannot be skipped) plus what happened to the bill afterwards:
payments and credit notes settled against it, notes and conversions made from
it, reminders sent. Newest first.

Draft saves come in bursts (autosave), so a run of edits by one person within
EDIT_RUN is shown as one entry: the net change from before the first save to
after the last.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast, Coalesce

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.india import place_name
from apps.core.tenancy import Principal
from apps.parties.models import Party
from apps.payments.models import Allocation
from apps.projects.models import Project
from apps.reminders.models import PaymentReminder

from ..models import Document
from ..pdf.render import TITLES, inr
from .drafts import get_document

EDIT_RUN = timedelta(minutes=30)
SAME_SAVE = timedelta(seconds=2)  # rows written without a request id (scripts, jobs)

# Document fields worth telling people about, in the order they are shown.
FIELDS: dict[str, str] = {
    "doc_date": "Date",
    "due_date": "Due date",
    "valid_until": "Valid until",
    "party_id": "Client",
    "project_id": "Project",
    "place_of_supply": "Place of supply",
    "reverse_charge": "Reverse charge",
    "notes": "Notes",
    "terms": "Terms",
    "grand_total": "Total",
}
MONEY = {"grand_total"}  # deductions follow from the lines: the total says enough
DATES = {"doc_date", "due_date", "valid_until"}
LINE_FIELDS: dict[str, str] = {
    "description": "description",
    "quantity": "quantity",
    "unit": "unit",
    "rate": "rate",
    "discount_amount": "discount",
    "gst_rate": "GST",
    "sac_hsn": "HSN/SAC",
}
MODES = {
    "BANK_TRANSFER": "bank transfer",
    "UPI": "UPI",
    "CHEQUE": "cheque",
    "CASH": "cash",
}


@dataclass
class Entry:
    at: datetime
    actor_id: uuid.UUID | None
    kind: str
    summary: str
    details: list[str] = field(default_factory=list)
    row: tuple[str, uuid.UUID] | None = None  # (table, id): its time is taken from the audit trail


@dataclass
class _Save:
    """The audit rows of one save: one request, or rows written together."""

    at: datetime
    actor_id: uuid.UUID | None
    request_id: str | None
    doc_old: dict[str, Any] | None = None
    doc_new: dict[str, Any] | None = None
    lines_before: dict[str, dict[str, Any]] = field(default_factory=dict)
    lines_after: dict[str, dict[str, Any]] = field(default_factory=dict)


def _decode(raw: str | None) -> dict[str, Any] | None:
    # Exact numbers: jsonb keeps 310.00 as written; a float would not.
    return None if raw is None else json.loads(raw, parse_float=Decimal, parse_int=Decimal)


def _rows(tenant_id: uuid.UUID, doc_id: uuid.UUID) -> list[dict[str, Any]]:
    data = {"old": Cast("old_data", TextField()), "new": Cast("new_data", TextField())}
    cols = ("id", "occurred_at", "actor_user_id", "request_id", "table_name", "row_id")
    doc_rows = AuditLog.objects.filter(
        tenant_id=tenant_id, table_name="documents", row_id=doc_id
    ).values(*cols, **data)
    line_rows = (
        AuditLog.objects.annotate(
            document_ref=Coalesce(KT("new_data__document_id"), KT("old_data__document_id"))
        )
        .filter(tenant_id=tenant_id, table_name="document_lines", document_ref=str(doc_id))
        .values(*cols, **data)
    )
    rows = [*doc_rows, *line_rows]
    rows.sort(key=lambda r: r["id"])  # the order they were written
    return rows


def _saves(rows: list[dict[str, Any]]) -> list[_Save]:
    saves: list[_Save] = []
    lines: dict[str, dict[str, Any]] = {}  # the bill's lines as of now, by row id
    for r in rows:
        last = saves[-1] if saves else None
        same = last is not None and (
            (r["request_id"] is not None and r["request_id"] == last.request_id)
            or (
                r["request_id"] is None
                and last.request_id is None
                and r["actor_user_id"] == last.actor_id
                and r["occurred_at"] - last.at <= SAME_SAVE
            )
        )
        if not same or last is None:
            last = _Save(r["occurred_at"], r["actor_user_id"], r["request_id"])
            last.lines_before = dict(lines)
            saves.append(last)
        old, new = _decode(r["old"]), _decode(r["new"])
        if r["table_name"] == "documents":
            if last.doc_old is None:
                last.doc_old = old
            last.doc_new = new
        else:
            key = str(r["row_id"])
            if new is None:
                lines.pop(key, None)
            else:
                lines[key] = new
        last.lines_after = dict(lines)
    return saves


def _num(value: Any) -> str:
    return "" if value is None else f"{Decimal(value).normalize():f}"


def _money(value: Any) -> str:
    return "₹" + inr(Decimal(value).quantize(Decimal("0.01")))


def _day(value: str | None) -> str:
    if not value:
        return "none"
    d = date.fromisoformat(value)
    return f"{d.day} {d:%b %Y}"


class _Names:
    """Clients and projects by id, looked up once for the whole history."""

    def __init__(self, saves: list[_Save]) -> None:
        parties: set[str] = set()
        projects: set[str] = set()
        for s in saves:
            for d in (s.doc_old, s.doc_new):
                if d:
                    parties.add(d["party_id"])
                    if d.get("project_id"):
                        projects.add(d["project_id"])
        self.parties = {
            str(k): v
            for k, v in Party.objects.filter(pk__in=parties).values_list("id", "display_name")
        }
        self.projects = {
            str(k): f"{c} {n}" if n and n != c else c
            for k, c, n in Project.objects.filter(pk__in=projects).values_list("id", "code", "name")
        }

    def show(self, name: str, value: Any) -> str:
        if value is None or value == "":
            return "none"
        if name == "party_id":
            return str(self.parties.get(value, "a deleted client"))
        if name == "project_id":
            return self.projects.get(value, "a deleted project")
        if name in MONEY:
            return _money(value)
        if name in DATES:
            return _day(value)
        if name == "place_of_supply":
            return f"{value} {place_name(value)}"
        if name == "reverse_charge":
            return "yes" if value else "no"
        if name in ("notes", "terms"):
            text = str(value)
            return f'"{text[:60]}…"' if len(text) > 60 else f'"{text}"'
        return str(value)


def _doc_changes(before: dict[str, Any], after: dict[str, Any], names: _Names) -> list[str]:
    out = []
    for name, label in FIELDS.items():
        old, new = before.get(name), after.get(name)
        if old != new and not (name in MONEY and Decimal(old or 0) == Decimal(new or 0)):
            out.append(f"{label}: {names.show(name, old)} → {names.show(name, new)}")
    return out


def _line_value(name: str, value: Any) -> str:
    if value is None or value == "":
        return "none"
    if name in ("rate", "discount_amount"):
        return _money(value)
    if name == "quantity":
        return _num(value)
    if name == "gst_rate":
        return f"{_num(value)}%"
    return str(value)


def _ordered(lines: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(lines.values(), key=lambda ln: int(ln["line_no"]))


def _line_changes(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[str]:
    """Lines are written afresh on every save, so they are matched by
    description (then by position): removing line 2 is one change, not a
    change to every line below it."""
    old, new = _ordered(before), _ordered(after)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmatched_old = list(old)
    unmatched_new: list[dict[str, Any]] = []
    for ln in new:
        match = next((o for o in unmatched_old if o["description"] == ln["description"]), None)
        if match is None:
            unmatched_new.append(ln)
        else:
            unmatched_old.remove(match)
            pairs.append((match, ln))
    for ln in list(unmatched_new):
        match = next((o for o in unmatched_old if o["line_no"] == ln["line_no"]), None)
        if match is not None:
            unmatched_old.remove(match)
            unmatched_new.remove(ln)
            pairs.append((match, ln))
    out: list[str] = []
    for o in unmatched_old:
        out.append(f'Removed line {_num(o["line_no"])} "{o["description"]}"')
    for o, n in sorted(pairs, key=lambda p: int(p[1]["line_no"])):
        changed = [
            f"{label} {_line_value(f, o.get(f))} → {_line_value(f, n.get(f))}"
            for f, label in LINE_FIELDS.items()
            if _differs(o.get(f), n.get(f))
        ]
        if changed:
            out.append(f'Line {_num(n["line_no"])} "{o["description"]}": ' + ", ".join(changed))
    for n in unmatched_new:
        qty = f"{_num(n['quantity'])} {n.get('unit') or ''}".strip()
        out.append(
            f'Added line {_num(n["line_no"])} "{n["description"]}": {qty} at {_money(n["rate"])}'
        )
    return out


def _differs(a: Any, b: Any) -> bool:
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a != b
    return (a or None) != (b or None)


def _number(d: dict[str, Any]) -> str:
    title = TITLES.get(d["doc_type"], "Document").lower()
    return f"{title} {d['doc_number']}" if d.get("doc_number") else f"draft {title}"


def _from_saves(saves: list[_Save], names: _Names) -> list[Entry]:
    entries: list[Entry] = []
    run: tuple[_Save, _Save] | None = None  # first and last save of a run of edits

    def close_run() -> None:
        nonlocal run
        if run is None:
            return
        first, last = run
        run = None
        details = _doc_changes(first.doc_old or {}, last.doc_new or first.doc_old or {}, names)
        details += _line_changes(first.lines_before, last.lines_after)
        if details:
            entries.append(Entry(last.at, last.actor_id, "edited", "Edited the draft", details))

    for s in saves:
        old, new = s.doc_old, s.doc_new
        if old is None and new is not None:  # created
            close_run()
            lines = _ordered(s.lines_after)
            summary = f"Created the {_number(new)}"
            entries.append(
                Entry(
                    s.at,
                    s.actor_id,
                    "created",
                    summary,
                    [
                        f"{len(lines)} line{'' if len(lines) == 1 else 's'}, "
                        f"total {_money(new['grand_total'])}"
                    ],
                )
            )
            continue
        if old is not None and new is not None and old["status"] != new["status"]:
            close_run()
            entries.append(_status_entry(s, old, new, names))
            continue
        # a draft edit (or a save that only touched lines)
        if run is not None and s.actor_id == run[0].actor_id and s.at - run[1].at <= EDIT_RUN:
            run = (run[0], s)
        else:
            close_run()
            run = (s, s)
    close_run()
    return entries


def _status_entry(s: _Save, old: dict[str, Any], new: dict[str, Any], names: _Names) -> Entry:
    status = new["status"]
    if status == "ISSUED":
        details = _doc_changes(old, new, names)  # issuing may set the due date
        details = [d for d in details if not d.startswith("Total:")]
        return Entry(
            s.at,
            s.actor_id,
            "issued",
            f"Issued as {new['doc_number']}",
            [f"Total {_money(new['grand_total'])}", *details],
        )
    if status == "CANCELLED":
        reason = new.get("cancel_reason")
        return Entry(
            s.at, s.actor_id, "cancelled", "Cancelled", [f"Reason: {reason}"] if reason else []
        )
    if status == "ACCEPTED":
        return Entry(s.at, s.actor_id, "accepted", "Marked as accepted by the client")
    if status == "DECLINED":
        return Entry(s.at, s.actor_id, "declined", "Marked as declined by the client")
    return Entry(s.at, s.actor_id, "edited", f"Status changed to {status.lower()}")


def _written_at(tenant_id: uuid.UUID, entries: list[Entry]) -> None:
    """Times from the audit trail (the clock when each row was written), so the
    history is in the order things happened, even within one transaction.
    A note's time is when it was issued."""
    rows = [e.row for e in entries if e.row is not None]
    if not rows:
        return
    issued = {i for t, i in rows if t == "documents#issued"}
    found: dict[uuid.UUID, datetime] = {}
    audit = (
        AuditLog.objects.filter(
            tenant_id=tenant_id,
            table_name__in={t.partition("#")[0] for t, _ in rows},
            row_id__in={i for _, i in rows},
        )
        .annotate(status=KT("new_data__status"))
        .order_by("id")
        .values_list("row_id", "occurred_at", "status")
    )
    for row_id, at, status in audit:
        if row_id in found or (row_id in issued and status == "DRAFT"):
            continue
        found[row_id] = at
    for e in entries:
        if e.row is not None and e.row[1] in found:
            e.at = found[e.row[1]]


def _afterwards(doc: Document) -> list[Entry]:
    """What happened to the bill after it went out (not in its own rows)."""
    entries: list[Entry] = []
    allocations = Allocation.objects.filter(document_id=doc.pk).select_related(
        "payment", "credit_note"
    )
    for a in allocations:
        if a.payment is not None:
            p = a.payment
            how = ", ".join(x for x in (MODES.get(p.mode, p.mode.lower()), p.reference) if x)
            details = [f"Payment of {_money(p.amount)} on {_day(p.payment_date.isoformat())}"]
            if how:
                details.append(how)
            if p.status == "VOIDED":
                details.append("This payment was later voided")
            entries.append(
                Entry(
                    a.created_at,
                    a.created_by_id,
                    "payment",
                    f"Payment received: {_money(a.amount)}",
                    details,
                    ("allocations", a.pk),
                )
            )
        elif a.credit_note is not None:
            entries.append(
                Entry(
                    a.created_at,
                    a.created_by_id,
                    "payment",
                    f"{_money(a.amount)} settled by credit note {a.credit_note.doc_number}",
                    row=("allocations", a.pk),
                )
            )
    notes = Document.objects.filter(original_document_id=doc.pk).exclude(status="DRAFT")
    for n in notes:
        kind = "Credit" if n.doc_type == "CREDIT_NOTE" else "Debit"
        entries.append(
            Entry(
                n.issued_at or n.created_at,
                n.issued_by_id or n.created_by_id,
                "note",
                f"{kind} note {n.doc_number} issued against this bill",
                [f"Amount {_money(n.grand_total)}"]
                + ([f"Later cancelled: {n.cancel_reason}"] if n.status == "CANCELLED" else []),
                ("documents#issued", n.pk),
            )
        )
    for c in Document.objects.filter(source_document_id=doc.pk):
        made = TITLES.get(c.doc_type, "document").lower()
        what = f"{made} {c.doc_number}" if c.doc_number else f"draft {made}"
        entries.append(
            Entry(
                c.created_at,
                c.created_by_id,
                "converted",
                f"Made into a {what}",
                row=("documents", c.pk),
            )
        )
    for r in PaymentReminder.objects.filter(document_id=doc.pk):
        entries.append(
            Entry(
                r.sent_at,
                r.sent_by_id,
                "reminder",
                f"Payment reminder emailed to {r.sent_to}",
                [f"Amount due {_money(r.amount_due)}"],
                ("payment_reminders", r.pk),
            )
        )
    return entries


def document_history(principal: Principal, doc_id: uuid.UUID) -> list[dict[str, Any]]:
    doc = get_document(principal, doc_id)  # tenant.read; another tenant's bill: 404
    saves = _saves(_rows(doc.tenant_id, doc.pk))
    later = _afterwards(doc)
    _written_at(doc.tenant_id, later)
    entries = _from_saves(saves, _Names(saves)) + later
    if doc.source_document_id is not None and entries and entries[0].kind == "created":
        src = Document.objects.filter(pk=doc.source_document_id).first()
        if src is not None:
            what = f"{TITLES.get(src.doc_type, 'document').lower()} {src.doc_number or ''}".strip()
            entries[0].details.insert(0, f"Made from {what}")
    actors = {e.actor_id for e in entries if e.actor_id is not None}
    people = dict(User.objects.filter(pk__in=actors).values_list("id", "full_name"))
    entries.sort(key=lambda e: e.at, reverse=True)
    return [
        {
            "at": e.at,
            "actor_name": people.get(e.actor_id) if e.actor_id else None,
            "kind": e.kind,
            "summary": e.summary,
            "details": e.details,
        }
        for e in entries
    ]
