# Next features: analysis (Part B, 5 November 2026)

The owner's list of possible features, plus our own ideas, analysed but **not
built**. For each: is it useful for Indian construction businesses, what already
exists, size, what it depends on, the risks, and a recommendation.

Sizes: **small** = about a day, **medium** = 2–4 days, **large** = a week or more
(each including schema, API, web, tests and docs at today's standard).

## Money out (the biggest gap)

Today the product is strong on money **in** (bills, receipts, retention and TDS
deducted by clients) but money **out** is only "expenses": an expense has a
vendor, an amount and how much of it was paid, with no bills, no part payments
against several bills, and no TDS that **we** deduct.

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| **Payables, part 1: vendor bills, payments out, payables ageing, TDS s.194C deducted by us** | Yes, every contractor buys material and pays subcontractors; TDS deducted on payments to subcontractors is a legal duty (and its register feeds the 26Q return) | Vendors are parties; expenses (category, vendor, GST, ITC, amount paid, receipt file); the payments / allocations engine for money in | Large | Nothing new; mirrors documents, payments and allocations for the other direction | Doubles the accounting surface; TDS rates and thresholds (1 % / 2 %, ₹30,000 single / ₹1,00,000 a year) must be data, not code; does not file 26Q itself | **Do now** (first after the design work): it is the gap customers will notice first. Expenses stay for small spends |
| **Payables, part 2: subcontractor work orders and RA bills received** (against a BOQ, with retention and TDS deducted by us) | Yes for main contractors who sublet work (very common) | BOQ, RA billing logic, retention and TDS maths exist for bills out | Large | Part 1 | Subcontract BOQ is often a subset of the client's BOQ with different rates: keep it a separate list linked by item | **Do later**, straight after part 1 |
| Purchase orders | Useful for firms with a purchase department | Nothing | Medium | Part 1 | Small firms do not raise POs: must stay optional | **Do later**, on request |
| Material received vs used per site | Useful, but it is an inventory module | Material expenses per project | Large | Part 1, POs | Stock valuation and site transfers grow fast | **Skip** for now: a separate module if ever wanted |
| **Cash-flow forecast** (next 4–8 weeks: expected receipts against payables) | Yes, owners run out of cash, not profit | Receivables with due dates and reminders; dashboard | Medium | Payables part 1 (without it, only one side) | A forecast that looks exact but is not: show it as ranges with the bills behind each number | **Do later**, right after payables part 1 |

## Banking and payments

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| **Bank statement import** (CSV / Excel) with matching to payments by UTR, amount and date | Yes, a big time saver: today every receipt is typed in | Payments store the UTR / cheque number; one shared spreadsheet reader for imports; allocation "oldest first" | Medium | None (better with payables for money out) | Every bank's file differs: a column-mapping step, remembered per bank; never auto-allocate without a person confirming | **Do now** (second): independent, high value, builds on existing import code |
| Online payment link on bills and in the client portal (UPI / payment gateway), recorded automatically | Useful, clients pay faster | The PDF carries a UPI QR code with the exact amount (B.13); bank import (above) would record such payments | Medium–large | A payment-gateway merchant account (owner's), webhooks | Gateway fees (about 2 % on cards), KYC; webhook security for money-moving calls | **Do later**: needs the owner's gateway account; the QR plus bank import covers most of it |

## GST and compliance

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| **e-Invoice** (IRN + signed QR) | Required by law for B2B bills of businesses above ₹5 crore turnover | PDF has room for the QR; issue flow is stable; GSTR-1 export | Large | GSP / IRP credentials and sandbox (owner); answer to the open question about the first customers' turnover | Legal: an invoice without a valid IRN is not valid for those businesses; cancellation only within 24 hours | **Do later**, before the first customer above ₹5 crore |
| e-Way bill | Rarely for works contracts (services); needed for material sales over ₹50,000 moving by road | Nothing | Medium–large | e-Invoice (same portal family) | Little use for the target customers | **Skip** for now |
| GSTR-2B reconciliation (input tax credit on expenses / vendor bills) | Yes for the accountant: missing ITC is lost money | Expenses carry the vendor's GSTIN, GST amount and an "ITC eligible" flag | Medium | Payables part 1 (vendor bill numbers) | Matching rules (invoice number formats differ); the 2B file format changes | **Do later**, after payables part 1 |
| **CA / auditor login** (read-only, with exports) | Yes, every business shares books with its CA | Mostly: the **Viewer** role already reads everything and can make every export, including GSTR-1. Missing: an audit-log screen (the `audit.view` permission exists, there is no page) and a clear "Invite your CA" option | Small | — | A CA may work for several businesses: already supported (one account, many businesses) | **Do now** (small): "Invite your CA" (Viewer) plus an audit-log page for owner / admin |

## Construction workflow

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| Site diary with progress photos linked to RA bills (proof of work) | Yes, clients and government departments ask for photos with RA bills | Uploads (checked, virus-scanned) exist, linked to expenses only | Medium–large | The phone pass and installable app (D.14), since entries are made on site | Photo storage grows (resize on upload); privacy of site photos in the portal | **Do later**, after D.14 |
| Approval flow (engineer drafts → accountant checks → owner approves bills above a limit) | Useful for firms with many site engineers | Mostly: site engineers can only draft; issuing needs an accountant or above | Medium | Notifications (below) | Slows small firms: must be off by default | **Do later**, when a customer asks (unchanged from B.0) |
| Recurring bills (e.g. monthly equipment hire) | Some | Templates make a monthly bill in a few clicks | Medium | — | The owner ruled out recurring / subscription features (1 Nov 2026) | **Skip** (owner decision); templates cover it |
| Labour attendance and wages per site | Useful to some, but it is payroll | Labour costs can be recorded as expenses per project | Large | — | Wage and PF / ESI rules; daily data entry on site | **Skip** for now |

## Ease of adoption

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| **Import masters from Tally** (clients, vendors, items) | Yes, most target customers use Tally today; this lowers the cost of switching | Client and item import from Excel / CSV (B.2, B.3); Tally export (B.16) | Medium | — | Tally's XML varies by version: test with real exports from customers | **Do now** (third): helps every new customer |
| Notifications centre (quotation accepted in the portal, payment recorded, bill overdue) | Useful | Emails for reminders, invitations and sign-in codes; nothing in the app | Medium | The new header (D.5) for the bell | Too many notifications are ignored: few, useful kinds, read / unread per person | **Do later**, after the design work |
| Malayalam / Hindi interface | Useful for office staff and site engineers | Nothing (D.2 adds a font that shows both scripts) | Large | All screens settled (after the design work) | Every text must be translated and kept up to date; amounts and GST terms must stay exact | **Do later**, after the design work, starting with Malayalam |
| Guided first bill walkthrough | Yes, "no training needed" | The setup checklist on the first page (H.2) | Small–medium | The new bill editor (D.9) | Tours that cannot be skipped annoy | **Do later**, after D.9 |
| Sample data on / off for new businesses | Useful to explore safely | A sample-data script for the developer's demo (`seed_demo.py`) | Medium | — | Sample bills inside a real business would use up invoice numbers and appear in GST returns | **Do later, differently**: a separate **demo company** (one click, switch with the company menu, deletable), never mixed into the real one |

## Account and security

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| **"Make new recovery codes" button** | Yes; today codes can only be refreshed by turning 2-step sign-in off and on | 2-step sign-in, recovery codes, Account page | Small | — | Must ask for the password and a current code | **Do now** (small) |
| **Sign-in alerts by email from a new device** | Yes, cheap protection against stolen passwords | Sessions with device and IP are recorded and listed under Account | Small | Email (exists) | Alert fatigue: only for a device not seen before | **Do now** (small) |

## Running it as a business (when selling to other companies)

| Idea | Useful? | Exists already | Size | Depends on | Risks | Recommendation |
|---|---|---|---|---|---|---|
| Plans and usage limits per company | Needed to charge customers | Per-user and per-IP rate limits only | Large | The pricing decision (open question in `PROGRESS.md`) | Limits that block billing at month-end would hurt customers: warn, never block issuing | **Do later**, once pricing is decided |
| An admin console for support | Needed with more than a few customers | Logs with request ids; nothing else | Medium–large | Plans | A support login that can read every business is a big security risk: read-only, audited, with the customer's consent per session | **Do later** |

## Our own ideas

| Idea | Why | Size | Recommendation |
|---|---|---|---|
| **"Paid now" when issuing** (cash / UPI with the bill) | One screen instead of two for every counter or small job; recommended in B.0 but not built yet | Small | **Do now** |
| **Audit log page** (who changed what, filter by person / date / record) | The data is already recorded for every change; owners and CAs ask for it | Small | **Do now**, with the CA login |
| Project-level access for site engineers (see only their projects) | Larger firms do not want every engineer to see every client | Medium (a `project_members` table and one more database policy) | **Do later**, on request |
| Reminders and bills on WhatsApp sent by the system (WhatsApp Business API) | Indian clients answer WhatsApp before email | Medium | **Do later**: needs a verified Meta business account and costs per message (owner decision) |
| Month-end bulk actions (download all bills of a month as one zip, email statements to every client who owes money) | Saves an afternoon each month | Medium | **Do later** |
| GST TDS (s.51) reconciliation and Form 26AS import | Today only income-tax TDS is reconciled and certificates are typed in | Medium | **Do later** |
| Retention release letter (PDF and email) | Clients often want a formal request to release retention | Small | **Do later** |
| Download all my data (Excel and PDFs) | Trust: customers can leave with their data | Small–medium | **Do later**, before selling widely |
| Large text setting | Older office staff (recommended in B.0) | Small | **Inside D.2** (a text size setting next to dark mode) |

## Recommended order after the design work

1. Small and quick: **recovery codes button, sign-in alerts, "Paid now" when
   issuing, audit log page + "Invite your CA"** (about a week together).
2. **Payables part 1**: vendor bills, payments out, payables ageing, TDS
   deducted by us.
3. **Bank statement import** with matching.
4. **Import masters from Tally**.
5. Cash-flow forecast; payables part 2 (subcontractor work orders and RA bills
   received); GSTR-2B reconciliation.
6. When a customer needs them: e-invoice, approval flow, notifications, the
   Malayalam interface, site diary with photos.
