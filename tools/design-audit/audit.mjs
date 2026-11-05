// Design audit (docs/07-design-audit.md): opens every page of the web app at
// three sizes, saves a full-page screenshot of each, runs axe (WCAG 2.2 AA)
// and measures what the eye misses (sideways scrolling on a phone, small tap
// targets, tiny text, how many font sizes / colours / corner radii a page uses).
//
// Needs the demo running (scripts\demo-up.cmd) with the sample data
// (backend/scripts/seed_demo.py) and Microsoft Edge (no browser download).
//
//   cd tools/design-audit && npm ci
//   set AUDIT_EMAIL=... AUDIT_PASSWORD=... AUDIT_TOTP_SECRET=...      (the demo owner)
//   set AUDIT_PORTAL_EMAIL=... AUDIT_PORTAL_PASSWORD=...             (a client-portal user)
//   node audit.mjs ../../docs/design/before        (or ../../docs/design/after)
//   set AUDIT_THEME=dark                            (optional: audit the dark theme)
//   set AUDIT_ONLY=^(dashboard|documents)$         (optional: only these pages)
//
// Pages are visited one at a time in one browser tab, to keep memory low.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright-core";

const BASE = process.env.AUDIT_BASE ?? "http://localhost:5173";
const MAILPIT = process.env.AUDIT_MAILPIT ?? "http://127.0.0.1:8025";
const OUT = path.resolve(process.argv[2] ?? "../../docs/design/before");
const ONLY = process.env.AUDIT_ONLY ? new RegExp(process.env.AUDIT_ONLY) : null;
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "phone", width: 390, height: 844 },
];
const AXE_SIZES = new Set(["desktop", "phone"]);

// --- helpers ------------------------------------------------------------------------------

function env(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} (see the top of audit.mjs).`);
  return value;
}

/** RFC 6238 code for a base32 secret, from the next 30-second step (each code works once). */
async function freshTotp(secret) {
  const step = Math.floor(Date.now() / 30000);
  while (Math.floor(Date.now() / 30000) === step) await new Promise((r) => setTimeout(r, 500));
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const hmac = crypto.createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

async function mailCount(to) {
  const r = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
  return (await r.json()).messages_count ?? 0;
}

/** The 6-digit code in the newest email to `to`, once more than `before` emails exist. */
async function emailedCode(to, before) {
  for (let i = 0; i < 60; i++) {
    const r = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    const found = await r.json();
    if ((found.messages_count ?? 0) > before) {
      const m = await (await fetch(`${MAILPIT}/api/v1/message/${found.messages[0].ID}`)).json();
      const code = /\b(\d{6})\b/.exec(m.Text)?.[1];
      if (code) return code;
    }
    await new Promise((r2) => setTimeout(r2, 1000));
  }
  throw new Error(`No sign-in code emailed to ${to}`);
}

async function signIn(page, email, password, code) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Code").waitFor();
  await page.getByLabel("Code").fill(await code());
  await page.getByRole("button", { name: "Verify" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30000 });
}

/** API calls from inside the signed-in page (a fresh access token from the refresh cookie). */
async function apiGet(page, paths) {
  return page.evaluate(async (list) => {
    const refreshed = await fetch("/api/v1/auth/token/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const { access_token: token } = await refreshed.json();
    const out = {};
    for (const [key, p] of Object.entries(list)) {
      const r = await fetch(`/api/v1${p}`, { headers: { Authorization: `Bearer ${token}` } });
      out[key] = await r.json();
    }
    return out;
  }, paths);
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page
    .waitForFunction(() => !document.querySelector('[data-slot="skeleton"], .animate-pulse'), null, {
      timeout: 8000,
    })
    .catch(() => {});
  await page.waitForTimeout(400);
}

/** What the eye misses, measured in the page. */
function measure() {
  const vw = window.innerWidth;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const describe = (el) => {
    const label =
      el.getAttribute("aria-label") || el.textContent?.trim().replace(/\s+/g, " ").slice(0, 40) || "";
    return `${el.tagName.toLowerCase()}${label ? ` "${label}"` : ""}`;
  };
  const all = [...document.querySelectorAll("body *")].filter(visible);
  const overflowing = all
    .filter((el) => el.getBoundingClientRect().right > vw + 1)
    .filter((el) => !all.some((p) => p !== el && p.contains(el) && p.getBoundingClientRect().right > vw + 1))
    .slice(0, 6)
    .map(describe);
  // the innermost elements past the right edge: what makes the page scroll sideways
  const tooWide = all
    .filter((el) => el.getBoundingClientRect().right > vw + 1)
    .filter((el) => ![...el.children].some((c) => visible(c) && c.getBoundingClientRect().right > vw + 1))
    .slice(0, 6)
    .map((el) => `${describe(el)} [${Math.round(el.getBoundingClientRect().width)} px, class ${String(el.className).slice(0, 60)}]`);
  const targets = [
    ...document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="link"]'),
  ].filter(visible);
  const small = targets.filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width < 24 || r.height < 24;
  });
  const textEls = all.filter((el) =>
    [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()),
  );
  const fontSizes = new Set(textEls.map((el) => getComputedStyle(el).fontSize));
  const tiny = textEls.filter((el) => parseFloat(getComputedStyle(el).fontSize) < 12);
  const colours = new Set(textEls.map((el) => getComputedStyle(el).color));
  const radii = new Set(
    all.map((el) => getComputedStyle(el).borderTopLeftRadius).filter((r) => r !== "0px"),
  );
  const buttons = [...document.querySelectorAll("button")].filter(visible);
  const buttonHeights = new Set(buttons.map((b) => Math.round(b.getBoundingClientRect().height)));
  const tables = [...document.querySelectorAll("table")].filter(visible);
  return {
    pageHeight: document.documentElement.scrollHeight,
    sidewaysScroll: document.documentElement.scrollWidth > vw + 1,
    overflowing,
    tooWide,
    tapTargets: targets.length,
    smallTapTargets: small.length,
    smallTapExamples: small.slice(0, 5).map(describe),
    tinyText: tiny.length,
    fontSizes: [...fontSizes].sort((a, b) => parseFloat(a) - parseFloat(b)),
    textColours: colours.size,
    radii: [...radii],
    buttonHeights: [...buttonHeights].sort((a, b) => a - b),
    tables: tables.length,
    widestTable: Math.max(0, ...tables.map((t) => Math.round(t.getBoundingClientRect().width))),
    h1: [...document.querySelectorAll("h1")].filter(visible).map((h) => h.textContent.trim()),
  };
}

async function audit(page, pageDef, results, consoleErrors) {
  const entry = { name: pageDef.name, path: pageDef.path, sizes: {} };
  for (const size of SIZES.filter((s) => !pageDef.sizes || pageDef.sizes.includes(s.name))) {
    await page.setViewportSize({ width: size.width, height: size.height });
    consoleErrors.length = 0;
    await page.goto(`${BASE}${pageDef.path}`);
    await settle(page);
    if (pageDef.action) {
      await pageDef.action(page); // e.g. open a menu before the screenshot
      await settle(page);
    }
    const file = `${pageDef.slug}--${size.name}.jpg`;
    await page.screenshot({ path: path.join(OUT, file), fullPage: true, type: "jpeg", quality: 55 });
    const metrics = await page.evaluate(measure);
    let axe = null;
    if (AXE_SIZES.has(size.name)) {
      const found = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
        .analyze();
      axe = found.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
      }));
    }
    entry.sizes[size.name] = {
      screenshot: file,
      url: page.url().replace(BASE, ""),
      metrics,
      axe,
      consoleErrors: [...consoleErrors],
    };
    process.stdout.write(`  ${pageDef.slug} ${size.name}\n`);
  }
  results.push(entry);
}

// --- the pages ----------------------------------------------------------------------------

function staffPages(ids) {
  const p = (slug, name, url) => ({ slug, name, path: url });
  return [
    p("dashboard", "Dashboard (first page after sign-in)", "/"),
    p("documents", "Invoices & quotes list", "/documents"),
    p("document-new", "New bill (editor)", "/documents/new"),
    p("document-edit", "Draft bill in the editor", `/documents/${ids.anilDraft}/edit`),
    p("document-issued", "Issued bill (INV/0002)", `/documents/${ids.inv2}`),
    p("document-review", "Draft bill with the final review open", `/documents/${ids.lakshmiDraft}?review=1`),
    p("document-quotation", "Accepted quotation", `/documents/${ids.quotation}`),
    p("templates", "Templates", "/templates"),
    p("catalog", "Catalog", "/catalog"),
    p("payments", "Payments list", "/payments"),
    p("payment-new", "Record a payment", "/payments/new"),
    p("payment", "A payment", `/payments/${ids.payment}`),
    p("parties", "Parties list", "/parties"),
    p("party-new", "New party", "/parties/new"),
    p("party", "A client", `/parties/${ids.skyline}`),
    p("party-statement", "Statement of account", `/parties/${ids.skyline}/statement`),
    p("projects", "Projects list", "/projects"),
    p("project-new", "New project", "/projects/new"),
    p("project", "A project: details", `/projects/${ids.tower}`),
    p("project-boq", "A project: BOQ", `/projects/${ids.tower}/boq`),
    p("project-progress", "A project: progress", `/projects/${ids.tower}/progress`),
    p("project-retention", "A project: retention", `/projects/${ids.tower}/retention`),
    p("expenses", "Expenses list", "/expenses"),
    p("expense-new", "New expense", "/expenses/new"),
    p("expense", "An expense", `/expenses/${ids.expense}`),
    p("reports", "Reports", "/reports"),
    p("exports", "Exports", "/exports"),
    p("tds", "TDS certificates", "/tds-certificates"),
    p("settings-company", "Settings: company", "/settings/company"),
    p("settings-members", "Settings: members", "/settings/members"),
    p("settings-gst", "Settings: GST registrations", "/settings/gst-registrations"),
    p("settings-series", "Settings: number series", "/settings/series"),
    p("settings-print", "Settings: bill printing", "/settings/print"),
    p("settings-tally", "Settings: Tally export", "/settings/tally"),
    p("account", "Your account", "/account"),
    {
      ...p("menu-open", "Menu open on a phone", "/"),
      sizes: ["phone"],
      action: (page) => page.getByRole("button", { name: "Open the menu" }).click(),
    },
    {
      ...p("palette", "Command palette (Ctrl+K)", "/"),
      action: async (page) => {
        await page.keyboard.press("Control+k");
        await page.getByRole("combobox", { name: "Search, or jump to a page" }).waitFor();
        // ready to type at once (fails the audit if the box is not focused)
        await page.waitForFunction(() => document.activeElement?.getAttribute("role") === "combobox", null, { timeout: 5000 });
      },
    },
    {
      ...p("palette-search", "Command palette: searching", "/"),
      action: async (page) => {
        await page.keyboard.press("Control+k");
        await page.getByRole("combobox", { name: "Search, or jump to a page" }).fill("sky");
        await page.getByRole("group", { name: "Bills & quotations" }).waitFor();
      },
    },
  ];
}

function portalPages(ids) {
  const p = (slug, name, url) => ({ slug: `portal-${slug}`, name: `Client portal: ${name}`, path: url });
  return [
    p("overview", "overview", "/portal"),
    p("bills", "bills & quotes", "/portal/bills"),
    p("bill", "a bill", `/portal/bills/${ids.inv2}`),
    p("payments", "payments", "/portal/payments"),
    p("statement", "statement", "/portal/statement"),
    p("projects", "projects", "/portal/projects"),
    p("project", "a project", `/portal/projects/${ids.tower}`),
  ];
}

const PUBLIC = [
  { slug: "home", name: "Public home page", path: "/" },
  { slug: "login", name: "Sign in", path: "/login" },
  { slug: "signup", name: "Create account", path: "/signup" },
  { slug: "forgot-password", name: "Forgot password", path: "/forgot-password" },
  // the style guide (D.3): only in builds made with VITE_DESIGN_PAGE=true; AUDIT_DESIGN=1
  ...(process.env.AUDIT_DESIGN ? [{ slug: "design", name: "Design system (/design)", path: "/design" }] : []),
];

// --- run ----------------------------------------------------------------------------------

fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];
const wanted = (list) => (ONLY ? list.filter((x) => ONLY.test(x.slug)) : list);

async function withContext(run) {
  const context = await browser.newContext({ viewport: SIZES[0], deviceScaleFactor: 1 });
  if (process.env.AUDIT_THEME) {
    // AUDIT_THEME=dark: the app's theme choice (D.2), set before every page loads
    await context.addInitScript((theme) => {
      window.localStorage.setItem("app.theme", theme);
    }, process.env.AUDIT_THEME);
  }
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 300)));
  try {
    await run(page, consoleErrors);
  } finally {
    await context.close();
  }
}

console.log("Public pages");
await withContext(async (page, errors) => {
  for (const def of wanted(PUBLIC)) await audit(page, def, results, errors);
});

console.log("Staff pages (demo owner)");
let ids = {};
await withContext(async (page, errors) => {
  const secret = env("AUDIT_TOTP_SECRET");
  await signIn(page, env("AUDIT_EMAIL"), env("AUDIT_PASSWORD"), () => freshTotp(secret));
  const found = await apiGet(page, {
    documents: "/documents?limit=100",
    parties: "/parties?limit=100",
    projects: "/projects?limit=100",
    payments: "/payments?limit=10",
    expenses: "/expenses?limit=10",
  });
  const docs = found.documents.results;
  ids = {
    inv2: docs.find((d) => d.doc_number === "INV/0002")?.id,
    quotation: docs.find((d) => d.doc_type === "QUOTATION")?.id,
    anilDraft: docs.find((d) => d.status === "DRAFT" && d.party_name === "Anil Kumar")?.id,
    lakshmiDraft: docs.find((d) => d.status === "DRAFT" && d.party_name === "Lakshmi Traders")?.id,
    skyline: found.parties.results.find((x) => x.display_name === "Skyline Developers")?.id,
    tower: found.projects.results.find((x) => x.code === "SKY-TOWER")?.id,
    payment: found.payments.results[0]?.id,
    expense: found.expenses.results[0]?.id,
  };
  const missing = Object.entries(ids).filter(([, v]) => !v).map(([k]) => k);
  if (missing.length) throw new Error(`Demo data missing: ${missing.join(", ")} (run seed_demo.py)`);
  for (const def of wanted(staffPages(ids))) await audit(page, def, results, errors);
});

if (process.env.AUDIT_PORTAL_EMAIL) {
  console.log("Client portal pages");
  await withContext(async (page, errors) => {
    const email = env("AUDIT_PORTAL_EMAIL");
    const before = await mailCount(email);
    await signIn(page, email, env("AUDIT_PORTAL_PASSWORD"), () => emailedCode(email, before));
    for (const def of wanted(portalPages(ids))) await audit(page, def, results, errors);
  });
}

await browser.close();
fs.writeFileSync(
  path.join(OUT, "results.json"),
  JSON.stringify({ base: BASE, at: new Date().toISOString(), sizes: SIZES, pages: results }, null, 1),
);
console.log(`Done: ${results.length} pages, ${results.reduce((n, r) => n + Object.keys(r.sizes).length, 0)} screenshots in ${OUT}`);
