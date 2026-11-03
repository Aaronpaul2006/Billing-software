# Billing ideas: analysis (STEP 0, 2026-11-03)

Ideas the owner asked to have analysed, not built yet (point 7 of the billing
brief), plus a few of our own. For each: is it useful for construction
billing, what already exists, rough size, what it depends on, and a
recommendation. Sizes: small = about a day, medium = 2–4 days, large = a week
or more.

| Idea | Useful? | Exists already | Size | Depends on | Recommendation |
|---|---|---|---|---|---|
| Recent and favourite items at the top of the item search | Yes: most offices bill the same 20 items | Nothing; the editor lists every catalog item in a dropdown | Small (recent: from past lines, no schema); favourites need a column | B.1 item search | **Do now, recent only** (inside B.1); favourites later if asked: recent covers most of it with no clicks |
| Client / project price lists (e.g. a government rate list) | Yes for government / PWD work and repeat clients | Partly: a project's **BOQ is its rate list** (lines from the BOQ take its rate); "last rate for this client" (B.8) covers repeat clients | Medium (new table, picking order: client list → catalog) | B.1, B.8 | **Do later**: BOQ + last rate cover most cases; build when a client with a fixed schedule of rates appears |
| Due date from the client's payment terms (e.g. 30 days) | Yes: fewer missed due dates, better overdue figures and reminders | No; due date is typed by hand | Small (a `payment_terms_days` on the client, default on new bills) | — | **Do now**: tiny, and it makes the dashboard's overdue list and the reminders right |
| Approval flow: engineer drafts → accountant issues → owner approves above an amount | Useful for firms with many site engineers | Partly: roles already enforce it (site engineers can only draft; issuing needs an accountant or above) | Medium–large (an approval state, a threshold setting, notifications) | Final review (B.14) | **Do later**: today's role split covers most of it; add the owner's threshold when a customer asks |
| Number prefix per project (VILLA/001) | Nice for clients, but optional | Series per GSTIN, type and financial year; GST allows several series | Medium (pick the series by project; today one series is active per GSTIN / type / year, enforced in the database) | — | **Do later**: changes the numbering rules; low value against the risk |
| Undo the last few changes on a draft | Nice | No; but drafts are never lost (autosave, B.6) and history shows changes (B.11) | Small–medium (an undo stack in the editor) | B.4, B.6 | **Do later** |
| "Paid now" at issue (cash / UPI with the bill) | Yes for small jobs and counter sales | Payments and allocations exist, separately | Small (one step: issue, then record a payment allocated to it; one screen) | B.14 | **Do now** (right after the B steps): saves a second screen for every cash bill |
| Bulk actions at month-end (email / download many bills) | Yes at month-end | Registers export to Excel; no bulk PDFs or bulk email | Medium (a background job that zips PDFs; bulk email) | B.13, B.15 | **Do later** |
| Malayalam / Hindi labels on screen and on the PDF | Useful for staff and some clients | No | Large (every screen's text, Indian-language fonts in the PDF, translations to maintain) | B.13 | **Do later**: do it once the screens have settled, or the work is done twice |
| Large text mode for older staff | Yes, cheap | No (browser zoom works today) | Small (a switch that scales the whole app; remembered per person) | — | **Do now**: a few hours |
| Guided first bill (a short walkthrough the first time) | Yes, fits "no training needed" | Partly: the H.2 setup checklist | Small–medium | B.4 (the new screen must settle first) | **Do later**, straight after the B steps |
| e-Invoice (IRN + QR) | Required by law for turnover above ₹5 crore | No | Large (IRP / GSP API, credentials, sandbox, cancellation within 24 h) | B.13 PDF (QR), stable issue flow | **Do later**: needed before selling to bigger contractors; not for the first customers |
| e-Way bill | Rarely: works-contract service bills move no goods; only material sales above ₹50,000 | No | Medium–large | e-Invoice | **Skip for now** |
| Recurring bills (e.g. monthly equipment hire) | Some | Templates (W.3) make a monthly bill in a few clicks | Medium | — | **Skip**: the owner ruled out recurring / subscription features (2026-11-01); templates cover it |
| Material stock per site (issued vs used) | Useful, but it is an inventory module, not billing | Expenses record material bought per project | Large | — | **Skip** for billing; a separate module if ever wanted |

## Our own ideas

| Idea | Why | Size | Recommendation |
|---|---|---|---|
| Item search also finds BOQ items, by code or words | On RA bills, people think in BOQ item numbers ("2.3") | Small | **In B.1** |
| Remember the last project per client | Most clients have one running project | Small | **In B.4** |
| Show the client's balance and overdue amount on the bill screen | Stops new bills to clients who have not paid | Small (statement data exists) | **In B.4** |
| Print on letterhead (top margin, no logo) as a third layout | Many firms have printed letterheads | Small | **Ask** when building B.13 |
| Check the client's GSTIN format and state as it is typed | Wrong GSTINs break GSTR-1 | Exists on the server; show it live | **In B.1** (client popup) |
| Shortcuts that do not fight the browser | F-keys like Tally's F8 reload or open help in browsers | — | Use Alt / Ctrl shortcuts, listed in the help panel (B.4) |

## A note on two of the requested warnings

- "GST charged to a client without GSTIN": charging GST to an unregistered
  client is correct (a B2C supply). The useful warning is the other way round:
  a **registered** business client with **no GSTIN saved**, so they cannot
  claim input tax credit and the bill lands in GSTR-1 as B2C. We will word
  the warning that way.
- "Possible duplicate bill": same client, total within 1 %, issued in the
  last 7 days. A warning only; the user decides.
