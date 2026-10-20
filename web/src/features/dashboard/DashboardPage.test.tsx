import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const totals = (billed: string) => ({
  billed,
  taxable: "292200.00",
  tax: "51996.00",
  collected: "305000.00",
  expenses: "90640.00",
  outstanding: "34280.00",
});

const receivables = {
  results: [
    {
      party_id: "0192f5c4-0000-7000-8000-0000000000c1",
      display_name: "Skyline Developers",
      document_count: 2,
      not_due: "10600.00",
      days_1_30: "23680.00",
      days_31_60: "0.00",
      days_61_90: "0.00",
      days_90_plus: "0.00",
      total: "34280.00",
    },
  ],
  totals: {
    party_id: "00000000-0000-0000-0000-000000000000",
    display_name: "All parties",
    document_count: 2,
    not_due: "10600.00",
    days_1_30: "23680.00",
    days_31_60: "0.00",
    days_61_90: "0.00",
    days_90_plus: "0.00",
    total: "34280.00",
  },
};

describe("dashboard", () => {
  it("shows the period totals, the previous period and receivables", async () => {
    const queries: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/reports/summary`, ({ request }) => {
        queries.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          book: "ALL",
          period: {},
          previous_period: {},
          current: totals("344196.00"),
          previous: totals("120000.00"),
        });
      }),
      http.get(`${API}/reports/receivables`, () => HttpResponse.json(receivables)),
    );
    renderSignedIn("/");

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(await within(summary).findByText("₹3,44,196.00")).toBeInTheDocument();
    expect(within(summary).getByText("Previous period: ₹1,20,000.00")).toBeInTheDocument();
    expect(within(summary).getByText("₹3,05,000.00")).toBeInTheDocument();

    const party = await screen.findByRole("link", { name: "Skyline Developers" });
    expect(party).toHaveAttribute("href", "/parties/0192f5c4-0000-7000-8000-0000000000c1");
    expect(screen.getAllByText("₹34,280.00")).toHaveLength(3); // card, row total, footer

    expect(queries[0]?.get("book")).toBe("ALL");
    expect(queries[0]?.get("from")).toMatch(/^\d{4}-04-01$/); // this financial year
  });

  it("asks again when the period or book changes", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    server.use(
      http.get(`${API}/reports/summary`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        seen.push(`${q.get("book") ?? ""}:${q.get("from") ?? ""}`);
        return HttpResponse.json({
          book: "ALL",
          period: {},
          previous_period: {},
          current: totals("1.00"),
          previous: totals("0.00"),
        });
      }),
      http.get(`${API}/reports/receivables`, () =>
        HttpResponse.json({ results: [], totals: receivables.totals }),
      ),
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
      http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
    );
    renderSignedIn("/", { role: "SITE_ENGINEER" });
    expect(
      (await screen.findAllByText("Your role does not have access to this.")).length,
    ).toBeGreaterThan(0);
  });
});
