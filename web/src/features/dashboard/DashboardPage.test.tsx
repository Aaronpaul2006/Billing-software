import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Dashboard = components["schemas"]["Dashboard"];

const totals = (billed: string) => ({
  billed,
  collected: "305000.00",
  outstanding: "34280.00",
  overdue: "23680.00",
  expenses: "90640.00",
  margin: "-12000.00",
});

function dashboard(over: Partial<Dashboard> = {}): Dashboard {
  const months = Array.from({ length: 12 }, (_, i) => {
    const month = new Date(2025, 11 + i, 1);
    const iso = `${String(month.getFullYear())}-${String(month.getMonth() + 1).padStart(2, "0")}-01`;
    return { month: iso, billed: i === 10 ? "344196.00" : "0.00", collected: "0.00" };
  });
  return {
    book: "ALL",
    period: {},
    previous_period: {},
    totals: totals("344196.00"),
    previous: totals("120000.00"),
    months,
    overdue: {
      count: 1,
      results: [
        {
          document_id: "d1",
          doc_type: "TAX_INVOICE",
          doc_number: "INV/0007",
          party_id: "p1",
          party_name: "Skyline Developers",
          due_date: "2026-10-01",
          days_overdue: 32,
          outstanding: "23680.00",
          party_has_email: true,
          last_reminder_at: null,
        },
      ],
    },
    losing_projects: [
      {
        project_id: "pr1",
        code: "TOWER",
        name: "Tower",
        billed_taxable: "289000.00",
        cost: "400000.00",
        margin: "-111000.00",
      },
    ],
    drafts: {
      count: 1,
      results: [
        {
          id: "dr1",
          doc_type: "QUOTATION",
          doc_date: "2026-11-01",
          party_name: "Coastal Homes",
          grand_total: "59000.00",
          updated_at: "2026-11-01T10:00:00Z",
        },
      ],
    },
    ...over,
  };
}

const noReceivables = {
  results: [],
  totals: {
    party_id: "00000000-0000-0000-0000-000000000000",
    display_name: "All parties",
    document_count: 0,
    not_due: "0.00",
    days_1_30: "0.00",
    days_31_60: "0.00",
    days_61_90: "0.00",
    days_90_plus: "0.00",
    total: "0.00",
  },
};

describe("dashboard", () => {
  it("shows the totals, the year's chart, overdue bills, losing projects and drafts", async () => {
    const queries: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/reports/dashboard`, ({ request }) => {
        queries.push(new URL(request.url).searchParams);
        return HttpResponse.json(dashboard());
      }),
      http.get(`${API}/reports/receivables`, () => HttpResponse.json(noReceivables)),
    );
    renderSignedIn("/");

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(await within(summary).findByText("₹3,44,196.00")).toBeInTheDocument();
    expect(within(summary).getByText("Previous period: ₹1,20,000.00")).toBeInTheDocument();
    expect(within(summary).getByText("₹23,680.00")).toBeInTheDocument();
    expect(within(summary).getByText("1 bill past due")).toBeInTheDocument();
    expect(within(summary).getByText("-₹12,000.00")).toBeInTheDocument();

    expect(screen.getByRole("img", { name: "Billed and collected, last 12 months" })).toBeVisible();
    expect(screen.getByRole("link", { name: "INV/0007" })).toHaveAttribute("href", "/documents/d1");
    expect(screen.getByText("32 days")).toBeInTheDocument();
    expect(screen.getByText("-₹1,11,000.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Quotation · Coastal Homes" })).toHaveAttribute(
      "href",
      "/documents/dr1/edit",
    );

    expect(queries[0]?.get("book")).toBe("ALL");
    expect(queries[0]?.get("from")).toMatch(/^\d{4}-04-01$/); // this financial year
  });

  it("sends a reminder for an overdue bill, once per click", async () => {
    const user = userEvent.setup();
    const keys: (string | null)[] = [];
    server.use(
      http.get(`${API}/reports/dashboard`, () => HttpResponse.json(dashboard())),
      http.get(`${API}/reports/receivables`, () => HttpResponse.json(noReceivables)),
      http.post(`${API}/documents/d1/reminders`, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    renderSignedIn("/");
    await user.click(await screen.findByRole("button", { name: "Send reminder" }));
    expect(await screen.findByText("Reminder sent")).toBeInTheDocument();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toBeTruthy();
  });

  it("cannot remind a client without an email address", async () => {
    const base = dashboard();
    const row = base.overdue.results[0];
    if (!row) throw new Error("fixture");
    server.use(
      http.get(`${API}/reports/dashboard`, () =>
        HttpResponse.json({
          ...base,
          overdue: { count: 1, results: [{ ...row, party_has_email: false }] },
        }),
      ),
      http.get(`${API}/reports/receivables`, () => HttpResponse.json(noReceivables)),
    );
    renderSignedIn("/");
    expect(await screen.findByRole("button", { name: "Send reminder" })).toBeDisabled();
    expect(screen.getByText("No email address")).toBeInTheDocument();
  });

  it("asks again when the period or book changes", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    server.use(
      http.get(`${API}/reports/dashboard`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        seen.push(`${q.get("book") ?? ""}:${q.get("from") ?? ""}`);
        return HttpResponse.json(dashboard({ totals: totals("1.00") }));
      }),
      http.get(`${API}/reports/receivables`, () => HttpResponse.json(noReceivables)),
    );
    renderSignedIn("/");
    expect(await screen.findByText("Nothing outstanding.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Book"), "GST");
    await user.selectOptions(screen.getByLabelText("Period"), "this_month");
    await screen.findAllByText("₹1.00");
    expect(seen.some((s) => s.startsWith("GST:"))).toBe(true);
    expect(seen.at(-1)).toMatch(/^GST:\d{4}-\d{2}-01$/);
  });

  it("tells site engineers their role cannot see reports", async () => {
    server.use(
      http.get(`${API}/reports/dashboard`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
    );
    renderSignedIn("/", { role: "SITE_ENGINEER" });
    expect(
      (await screen.findAllByText("Your role does not have access to this.")).length,
    ).toBeGreaterThan(0);
  });
});
