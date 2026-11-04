# Demo: sample data and things to try

A local demo of the billing features on this PC, with a business full of
sample data. Nothing here is for production.

## 1. Start the servers

Docker Desktop must be running.

```bash
docker compose up -d                          # Postgres, Redis, storage, Mailpit
docker compose --profile app up -d api worker # the API and the worker (PDFs, emails)
cd web && npm run dev                         # the web app on http://localhost:5173
```

The API in Docker renders PDFs with WeasyPrint (it does not run on Windows).
Emails go to Mailpit, http://127.0.0.1:8025, never to real inboxes.

To free memory afterwards: `docker compose --profile app stop api worker`.

## 2. Fill a demo business

```bash
cd backend
uv run python scripts/seed_demo.py --email you@example.com
```

It asks for a password (or reads `--password` / `DEMO_PASSWORD`).

- **A new email:** it signs up as the owner of "Demo Constructions",
  confirms the address from Mailpit and turns on 2-step sign-in. It prints
  the authenticator key and 10 recovery codes **once**: keep them. Sign in
  with a recovery code (each works once), or add the key to Google /
  Microsoft Authenticator ("Enter a setup key", time-based).
- **An existing account with 2-step sign-in:** pass its key with
  `--totp-secret` (or `DEMO_TOTP_SECRET`).
- A business that already has a GST registration is left alone.

What it adds, through the API like the web app (every rule applies):

| | |
|---|---|
| Business | Demo Constructions, Kochi; GSTIN `32AAKFD1234B1Z8`; number series INV/, QT/, PI/, CN/, DN/ for 2026-27 |
| Bill printing | a "DC" logo, SBI bank details, UPI ID `democonstructions@okaxis`, default terms |
| Clients | Skyline Developers (registered, Kerala), Green Valley Homes (registered, Karnataka: IGST), Anil Kumar (homeowner), Lakshmi Traders (unregistered, a firm's PAN) |
| Projects | SKY-TOWER and GV-VILLAS (5 % retention, 2 % TDS), ANIL-HOUSE |
| Items | 7 catalog items: concrete, brick masonry, plastering, tiles, painting, steel, cement |
| Bills | INV/0001 paid by bank transfer; INV/0002 part paid by UPI, with a measurement sheet; INV/0003 unpaid, with credit note CN/0001; QT/0001 accepted and made into a draft invoice; a draft for Lakshmi Traders |

## 3. Things to try

- **Open INV/0002, then the PDF:** the measurement rows under the brick
  masonry line (walls, less the door openings), the HSN summary, the bank
  box and the UPI QR code for the exact amount still to pay.
- **On the same bill, choose a copy, then Print or Email…:** "Copy to print"
  labels it Original / Duplicate / Triplicate. Email sends the PDF; the
  email lands in Mailpit at http://127.0.0.1:8025. WhatsApp downloads the
  PDF and opens a ready message.
- **See the Change history at the bottom of any bill:** who created, edited,
  issued it, the payments, the credit note, the email.
- **Make an October export under Exports → Tally:** an XML file of sales,
  the credit note and receipts. The ledger names are in Settings → Tally
  export; the export's notes list the ledgers to create in Tally first.

More:

- **The draft for Lakshmi Traders → Issue…:** the final review warns that
  the client has no GSTIN (and its PAN is a firm's), that there is no due
  date, and that cement at ₹250 is far below the usual ₹380.
- **The draft invoice for Anil Kumar** (made from QT/0001): edit it with the
  keyboard (Enter moves on, Alt+N adds a line, Ctrl+Enter saves and opens
  the review).
- **Settings → Bill printing:** switch the layout to Simple and open a new
  bill's PDF; bills issued before keep the look they were issued with.
- **INV/0003 → Alter…:** the plain-words choices for changing an issued
  bill (credit note, debit note, cancel and make a corrected copy).
