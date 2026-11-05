# Design audit (A.0, 5 November 2026)

What the web app looks like today, page by page, before the design work.
Screenshots: [`docs/design/before/`](design/before/) (46 pages × desktop 1440,
tablet 768, phone 390 = 138 full-page images, named `<page>--<size>.jpg`).
Measurements and accessibility results for every page and size:
[`design/before/results.json`](design/before/results.json).

## How it was done

- `tools/design-audit/audit.mjs` (Playwright with the installed Edge, axe-core
  4.14): signs in to the demo business as the owner (2-step code) and as a
  client-portal user (emailed code), opens each page at the three sizes, waits
  for loading to finish, saves a full-page screenshot, runs axe with the WCAG
  2.0 / 2.1 / 2.2 A and AA rules plus best practices (desktop and phone), and
  measures what the eye misses: sideways scrolling, elements past the screen
  edge, tap targets smaller than 24 px, text smaller than 12 px, how many font
  sizes, text colours, corner radii and button heights a page uses, table widths.
- Data: the demo business from `backend/scripts/seed_demo.py`, plus a vendor,
  two expenses, six BOQ items and a portal user for Skyline Developers.
- Pages: 4 public, 35 staff, 7 client portal. Run again after each design step
  into `docs/design/after/`.

## The ten things that matter most

1. **No navigation on phones.** Below 768 px the sidebar is hidden and nothing
   replaces it: the top bar shows only the company name. On a phone you cannot
   reach another section, your account or Sign out except through links inside
   pages (`*--phone.jpg`, e.g. `documents--phone.jpg`). Templates and TDS
   certificates are not in the sidebar on any size.
2. **Tables are cut off on phones.** Every list and bill table keeps its desktop
   columns: on a 390 px screen the important columns (status, total,
   outstanding, amount) are off to the right inside a scroll area that is easy
   to miss and cannot be reached with the keyboard (tables up to 805 px wide:
   `documents--phone.jpg`, `document-issued--phone.jpg`, `project-boq--phone.jpg`,
   `portal-overview--phone.jpg`, `portal-statement--phone.jpg`).
3. **Five pages scroll sideways**: on tablet and phone the dashboard (6 tiles and
   the receivables table, `dashboard--phone.jpg` is 678 px wide), the bill editor
   (new and draft, `document-edit--phone.jpg`) and the project's progress tab; on
   phones also the project's retention tab.
4. **The bill editor is a form, not a grid.** Each line is a card with ten
   labelled boxes over two rows (~225 px per line on desktop, ~650 px on a phone);
   ten lines mean scrolling past 2,300 px. Totals and the Save buttons sit at the
   very bottom, not sticky. The line action icons spill past the card's right
   edge, and the ₹ / % discount selector is squashed to an unreadable "₹"
   (`document-edit--desktop.jpg`).
5. **Status has no colour meaning.** Issued, Accepted, Paid and Part paid all
   look the same (a black pill); a bill with ₹0.00 outstanding still says
   "Issued" (`documents--desktop.jpg`); Overdue is not a status at all in lists.
   Badges use the generic `default / outline / secondary` variants.
6. **The bill page has ten equal buttons and no clear next step.** PDF, copy
   label, Duplicate, Alter…, Print, Download, Email…, WhatsApp, Save as template
   are all outline buttons in three rows (four rows on a phone,
   `document-issued--phone.jpg`); for a draft only "Issue…" stands out.
7. **No brand and no colour.** The whole app is the default neutral grey theme:
   black primary buttons, grey borders, one green bar in the chart. No logo mark,
   no brand colour, the system font (Segoe UI on Windows; no Indian-language
   fallback chosen). Sign-in is a bare card on grey (`login--desktop.jpg`).
   Dark-mode colours are defined in `index.css` but never switched on.
8. **Dates are written five ways**: "25 Oct 2026", "4/11/2026, 8:21:32 am"
   (Issued, `document-issued--desktop.jpg`), "2026-11-04" (Settled by), "04-11-2026"
   (date boxes), "1 Apr – 5 Nov 2026" (dashboard). 13 files format dates locally
   with six separate helpers.
9. **Browser pop-ups for important choices.** Ten actions (delete draft, void a
   payment, revoke a member…) use the browser's `confirm()` box: unstyled, no
   explanation, no Undo. Success is shown as inline alerts that push the page
   down; there are no toasts.
10. **A real bug found on the way:** a project's **"Bill from"** shows "–"
    although the project has a GST registration (`project--desktop.jpg`). The
    select's options load after the form, so the browser shows the empty option;
    the stored value is right, but the screen is misleading and a save could
    send it empty. Fix in D.1.

---

## Findings by topic

### Layout

- **Dashboard order** (`dashboard--desktop.jpg`): greeting and quick actions,
  then the setup checklist, then the "Dashboard" heading; six KPI tiles of
  equal weight (Billed, Collected, Outstanding, Overdue, Expenses, Margin), each
  with "Previous period: ₹0.00" in small grey text even when there is nothing to
  compare. The three numbers an owner looks at first (to collect, overdue,
  collected this month) do not stand out. The chart leaves most of its width
  empty when there are only one or two months of data.
- **Page widths are inconsistent**: forms stop at 1030 px (`project--desktop.jpg`)
  or 935 px (`settings-print--desktop.jpg`) while lists use the full width; the
  public page's FAQ is narrower than its other sections (`home--desktop.jpg`).
- **Long single-column settings pages** (bill printing, Tally, account) with the
  Save button at the very end; each settings page is a separate sidebar item
  rather than one Settings area with tabs.
- **Bill page**: the facts card (party, project, place of supply, dates) is a
  grid of label / value pairs with no hierarchy; the change history is hidden
  at the very bottom.

### Typography

- Sizes in use: 10, 12, 14, 16, 18, 20, 24, 30 and 48 px (nine sizes; most
  pages use 3–4, the dashboard and home page 6). No defined type scale: headings
  are 24 px everywhere, card titles 16 px, labels 14 px, help text 12 px.
- **Tiny text**: 12 elements under 12 px on the dashboard (the 10 px "Previous
  period" lines and chart labels).
- Amounts use `tabular-nums` in most places (80 uses) and are right-aligned in
  tables (154 cells), but not in the dashboard's "Drafts waiting" list or the
  tiles, so digits do not line up.
- Help text under fields is very light grey and small (`project--desktop.jpg`:
  "Short and unique, e.g. VILLA-1.").

### Colour

- Only greys plus black; success / warning / danger / info colours exist only
  ad hoc (amber review warnings, red destructive text, green "Collected").
- Overdue amounts are not highlighted anywhere in lists.
- One contrast failure: the red "Overdue" figure in the home page's sample
  invoice (`home--desktop.jpg`, axe `color-contrast`, serious).

### Spacing and shape

- Corner radii in use: 4, 6, 8, 10, 14 and 16 px plus pills; cards 14 px,
  inputs and buttons 8 px. Button heights 16, 20, 32, 36 and 38 px (icon buttons
  on line rows are 16–20 px, too small to tap).
- Card padding and gaps vary between pages (24 px in forms, 16 px in the review
  panel); vertical rhythm differs between list, detail and form pages.

### Tables

- 26 files build tables by hand; no shared table: no sorting, no row actions
  menu, no density choice, no totals row (except receivables by party), no
  sticky header, no saved filters.
- Search on the bills list is by number only; filters are three native selects
  that wrap onto two rows on a phone.
- Empty tables say different things in different words (22 separate "No … yet"
  / "Nothing …" messages), most without a button to create the first item.
- On phones every table scrolls sideways inside its card (see above).

### Forms

- Native selects and date inputs (look different in each browser; the date
  boxes show `dd-mm-yyyy` placeholders); native file input ("Choose File / No
  file chosen", `settings-print--desktop.jpg`).
- The bill editor repeats every label on every line and adds a "Select line N"
  checkbox row per line; description often repeats the item name.
- Save buttons are at the end of long forms, never sticky; "Save draft" and
  "Save and keep working" sit next to Notes / Terms, far from the lines.
- Pickers (client, vendor, party) are text boxes with a "Change" button; their
  ARIA attributes point to a list that is not on the page (axe, critical).

### Empty, loading and error states

- Loading: skeletons in 36 files, but different shapes per page; some pages
  jump when data arrives (forms render after their selects load).
- Empty: plain sentences ("None.", "Nothing is past due.", "None sent yet.")
  with no illustration or next step; the dashboard shows two empty cards
  ("Overdue bills", "Projects losing money") taking space.
- Error: one `ErrorState` component, used consistently; form errors show under
  the fields. Success: inline alerts only.

### Navigation

- Sidebar is a flat list of 9 items plus 6 settings items; "Invoices & quotes"
  mixes two jobs; Templates and TDS certificates are not in it; "Parties" is
  the word used for clients and vendors.
- The same action has different names: "New bill" (dashboard) vs "New
  invoice" (bills list).
- No search across the app, no keyboard way to jump between sections, no
  breadcrumbs (detail pages have a single "← Back" link).
- The user menu is just the person's name at the bottom of the sidebar: nothing
  shows it opens a menu.

### Accessibility (axe, WCAG 2.2 AA)

| Rule | Impact | Where | Cause |
|---|---|---|---|
| `label-content-name-mismatch` | serious | 35 pages | The company switcher's accessible name is "Company" but it shows the company's name (`AppShell.tsx` `TenantSwitcher`, rendered twice) |
| `aria-valid-attr-value` | critical | New bill, Record a payment, New project, New / edit expense (`#party`, `#client`, `#vendor`) | Pickers set `aria-controls` / `aria-activedescendant` to a list id that is not in the page until the list opens |
| `scrollable-region-focusable` | serious | 7 pages on phones (bill, quotation, review, portal bill / payments / statement / project) | Table scroll areas cannot be reached with the keyboard |
| `color-contrast` | serious | Home page | Red sample figure on a light card |

Also seen: small tap targets on phones (up to 11 per page under 24 px: line
action icons, "Forgot password?", table links); focus rings exist (shadcn) but
are faint on grey backgrounds; every page has exactly one `h1`.

### Phone use (390 px)

- No navigation (finding 1), tables cut off (2), sideways scrolling on five pages (3).
- The bill editor becomes a ~3,400 px form (`document-edit--phone.jpg`); Notes and
  Terms are squeezed into a narrow column beside the totals.
- Action buttons wrap into 2–4 rows at the top of pages; no bottom action bar.
- The client portal's tabs scroll sideways with the last tab cut off
  (`portal-overview--phone.jpg`).
- Not installable (no web app manifest or icons).

---

## Page by page

Screenshot names are `<page>--desktop.jpg`, `--tablet.jpg`, `--phone.jpg`.
"Small taps" = tap targets under 24 px on the phone / all tap targets.

| Page (screenshots) | What is wrong | Small taps |
|---|---|---|
| Public home (`home`) | Generic grey look, no brand colour or logo mark; mock screens with window dots; FAQ narrower than the rest; one contrast failure | 2 / 10 |
| Sign in (`login`), Create account (`signup`), Forgot password (`forgot-password`) | Bare card on grey, product name as a small subtitle, no way back to the home page | 1–2 |
| Dashboard (`dashboard`) | Sideways scroll on tablet and phone; checklist before the heading; six equal tiles; tiny "Previous period" text; mostly empty chart; empty cards take space | 5 / 12 |
| Bills list (`documents`) | No colour per status, "Issued" for paid bills; search by number only; "New invoice" vs "New bill"; three native filters; on phones status / total / outstanding are cut off; no totals row | 7 / 15 |
| New bill, draft editor (`document-new`, `document-edit`) | Sideways scroll on tablet / phone; card per line with repeated labels; actions past the edge; squashed ₹ / % selector; totals and Save at the bottom; picker ARIA error | 5–11 / 66 |
| Issued bill (`document-issued`) | Ten equal buttons; "Issued" while part paid; three date formats; measurement rows not shown (PDF only); table cut on phones | 3 / 16 |
| Draft with review (`document-review`) | Review panel works well; "Due –" and "Project –" read as errors; buttons wrap on phones | 4 / 16 |
| Quotation (`document-quotation`) | Same button crowding; "Accepted" looks like "Issued" | 2 / 15 |
| Templates (`templates`), Catalog (`catalog`) | Not in the sidebar (templates); plain lists; catalog variants hard to scan | 0 |
| Payments, payment, record a payment (`payments`, `payment`, `payment-new`) | Lists cut on phones; allocation table wide; picker ARIA error on record | 0–2 |
| Parties, party, new party, statement (`parties`, `party`, `party-new`, `party-statement`) | "Parties" naming; list cut on phones; client page has no summary of what they owe at the top; 6 small taps on the list | 3–6 |
| Projects, project, new project, BOQ, progress, retention (`projects`, `project*`) | "Bill from" shows "–" (bug); progress tab scrolls sideways on tablet / phone, retention on phones; BOQ table cut on phones | 0–3 |
| Expenses, expense, new expense (`expenses`, `expense`, `expense-new`) | Vendor picker ARIA error; list cut on phones; native file input | 1 |
| Reports, Exports, TDS certificates (`reports`, `exports`, `tds`) | TDS not in the sidebar; long forms of selects; exports list plain | 0 |
| Settings pages (`settings-*`), Your account (`account`) | Six separate pages instead of one area with tabs; long single column; Save at the end; native file inputs on bill printing | 0–2 |
| Client portal (`portal-*`) | Tabs scroll sideways on phones (last tab cut); tables cut on phones (7 pages); plainer than the staff app but the same grey look | 0–3 |

## Baseline numbers (to compare after each step)

| Measure | Now |
|---|---|
| Pages with sideways scrolling (tablet / phone) | 4 / 5 |
| axe violations (serious + critical), all pages | 91 nodes, 4 rules |
| Tap targets under 24 px on phones, all pages | 75 |
| Font sizes in use | 9 |
| Corner radii in use | 6 + pills |
| First load (gzip): JS + CSS on the first page | 166 KB (`index` 135 KB, CSS 7 KB) |

## Progress against the baseline

| After step | Sideways scroll (tablet / phone) | axe serious + critical | Small taps (phone) | First load (gzip) |
|---|---|---|---|---|
| Before (A.0) | 4 / 5 | 91 nodes | 75 | 166 KB |
| D.1 | 4 / 5 | **0** | 75 | 168.8 KB |
| D.2 | 4 / 5 | 0 (light and dark) | 75 | 170.3 KB (+ fonts, cached) |
| D.3 | 4 / 5 | 0 (light and dark) | 75 | 172.7 KB |
| D.4 | 4 / 5 (bills list fixed; other lists in D.7) | 0 | 75 | 173.0 KB |
| D.5 | 4 / 5 | 0 | 75 | 174.9 KB |
| D.6 | 4 / 5 | 0 (light and dark) | 75 | 179.8 KB (see below) |
| D.7 | 4 / 5 (every list now cards on phones) | 0 (light and dark) | 3 on the 9 list pages (24 before) | 181.7 KB |
| D.8 | 4 / 5 (the bill's lines no longer cut off) | 0 (light and dark) | 3 on the 4 bill pages (13 before) | 181.8 KB |

From D.6 on, first load is measured with `tools/design-audit/first-load.mjs`
(every script and stylesheet `index.html` loads or preloads, gzip level 9), so
the figures can be repeated. Measured that way on the same commits: **before
170.4 KB, after D.5 178.6 KB, after D.6 179.8 KB (+5.5 %)**; the earlier rows
used a rougher sum and are a little lower. The command palette's contents load
the first time it opens (2.4 KB), not with the first page.

## Proposed design steps

In the recommended order; each is small enough to build, test, screenshot and
push on its own. Every step follows the A.5 quality bar: before / after
screenshots at three sizes, axe with no serious issues, AA contrast, visible
focus, keyboard only, existing tests green plus tests for new components, first
load within +10 % unless explained.

| Step | What | Why first / notes |
|---|---|---|
| **D.1** Fixes that need no design | Phone navigation (a menu button opening the sidebar as a drawer, with Sign out); company-switcher and picker accessibility errors; keyboard-reachable table scroll areas; the "Bill from" bug; one date format helper (`lib/dates.ts`: "25 Oct 2026", "25 Oct 2026, 8:21 am") used everywhere | Real defects; the phone is unusable without navigation |
| **D.2** Design tokens and type | Brand colour and neutrals, success / warning / danger / info, spacing, radius, shadows and a type scale as CSS variables in one place (`index.css` + `brand.ts`); a font with Malayalam / Hindi fallback (Noto Sans family, loaded only for those scripts) and tabular figures; light and dark mode (system setting, with a switch in the user menu) | Everything after builds on these |
| **D.3** Core components and the `/design` page | `PageHeader` with actions, `StatusBadge` (Draft, Issued, Paid, Part paid, Overdue, Cancelled, Accepted, Declined: one colour each, also the bill's payment state), `MoneyCell`, `FormSection`, sticky `SaveBar`, `ConfirmDialog` (replaces the ten `confirm()` boxes), `Toast` with Undo where the API allows it; a dev-only `/design` page showing every component and state | One source of truth before touching screens |
| **D.4** `DataTable` | Sticky header, sorting, row actions menu, density toggle, totals row, empty state with a call to action, skeleton rows, and **cards instead of columns on phones**; saved filters per list (kept per person in the browser) | Fixes the phone tables everywhere at once |
| **D.5** Navigation | Sidebar grouped by job (Sell, Money, Work, Insight, Settings), only what the role can use; breadcrumbs; "?" shortcut help | Small once D.1 has the drawer |
| **D.6** Command palette (Ctrl+K) | Bills by number, clients, projects, items; actions ("New bill", "Record payment", "Go to GST summary"); keyboard only; server-backed: one new `GET /search` endpoint (tenant-scoped, cross-tenant tested) | The only step that touches the API |
| **D.7** Lists | Bills, payments, expenses, clients, projects, catalog and the portal lists on `DataTable` with totals rows and saved filters; one name per action ("New bill") | Uses D.4 |
| **D.8** Bill page | Status timeline (Draft → Issued → Part paid → Paid), one primary action per state, the rest in a "More" menu, measurement rows shown, history easier to find | The screen used most after the editor |
| **D.9** Bill editor | Spreadsheet-like line grid (one row per line, labels once in the header, Tally keys kept), sticky totals and Save bar, optional live PDF preview beside it on wide screens | Largest step; after the components settle |
| **D.10** Dashboard | The three numbers that matter first, then the chart, then lists; fits a phone without sideways scrolling | |
| **D.11** Settings | One Settings area with left tabs (company, members, GST, series, bill printing, Tally, your account) | |
| **D.12** Client portal | The same design system, simpler: cards on phones, tabs that fit | |
| **D.13** Public home and sign-in | Brand, trust (security, contact), fast | |
| **D.14** Phone and PWA | Final pass at 390 px (bottom action bar on detail pages), installable app (manifest, icons, splash), static assets cached, never API data | Last, when every screen is final |
