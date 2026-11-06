import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function week(start: string, end: string, over: Record<string, unknown> = {}) {
  return {
    start,
    end,
    money_in: "0.00",
    money_out: "0.00",
    bills_in: [],
    bills_out: [],
    balance_low: "100000.00",
    balance_high: "100000.00",
    ...over,
  };
}

function forecast(over: Record<string, unknown> = {}) {
  return {
    as_of: "2026-11-06",
    cash_today: "200000.00",
    cash_sources: ["HDFC 1234 on 05 Nov 2026"],
    overdue_in: "323680.00",
    overdue_out: "58500.00",
    weeks: [
      week("2026-11-02", "2026-11-08", {
        money_out: "158500.00",
        bills_out: [
          {
            id: "vb1",
            kind: "VENDOR_BILL",
            number: "RK/101",
            party_name: "Ravi Kumar",
            due_date: "2026-11-07",
            outstanding: "158500.00",
          },
        ],
        balance_low: "-17000.00",
        balance_high: "306680.00",
      }),
      week("2026-11-09", "2026-11-15", {
        money_in: "323680.00",
        bills_in: [
          {
            id: "d1",
            kind: "BILL",
            number: "INV/0007",
            party_name: "Skyline Developers",
            due_date: "2026-11-10",
            outstanding: "323680.00",
          },
          {
            id: "r1",
            kind: "RETENTION_RELEASE",
            number: "SKY/RET/1",
            party_name: "Skyline Developers",
            due_date: "2026-11-12",
            outstanding: "0.00",
          },
        ],
        balance_low: "306680.00",
        balance_high: "630360.00",
      }),
    ],
    lowest_week_start: "2026-11-02",
    lowest_balance: "-17000.00",
    ...over,
  };
}

describe("cash-flow forecast (Part B)", () => {
  it("shows cash now, the lowest week, each week's range and its bills", async () => {
    const asked: (string | null)[] = [];
    server.use(
      http.get(`${API}/reports/cash-flow`, ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("weeks"));
        return HttpResponse.json(forecast());
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/cash-flow");
    expect(await screen.findByRole("heading", { name: "Cash flow" })).toBeInTheDocument();
    expect(await screen.findByText("HDFC 1234 on 05 Nov 2026")).toBeInTheDocument();
    expect(screen.getAllByText("₹2,00,000.00").length).toBeGreaterThan(0);
    expect(screen.getByText("Week of 2 Nov – 8 Nov")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Cash flow by week" });
    expect(within(table).getAllByText("-₹17,000.00").length).toBeGreaterThan(0);

    await user.click(within(table).getByRole("button", { name: "2 bills, 9 Nov – 15 Nov" }));
    const panel = await screen.findByRole("dialog", { name: "Week of 9 Nov – 15 Nov" });
    const coming = within(panel).getByRole("region", { name: "Coming in" });
    expect(within(coming).getByRole("link", { name: "INV/0007" })).toHaveAttribute(
      "href",
      "/documents/d1",
    );
    expect(within(coming).getByText("Retention release SKY/RET/1")).toBeInTheDocument();
    expect(within(panel).getByText("No vendor bills fall due.")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await user.selectOptions(screen.getByLabelText("Weeks to show"), "13");
    await waitFor(() => {
      expect(asked).toEqual(["8", "13"]);
    });
  });

  it("says when there is no bank statement to start from", async () => {
    server.use(
      http.get(`${API}/reports/cash-flow`, () =>
        HttpResponse.json(forecast({ cash_today: null, cash_sources: [] })),
      ),
    );
    renderSignedIn("/cash-flow");
    expect(await screen.findByText(/No bank statement yet/)).toBeInTheDocument();
    expect(screen.getByText("Lowest point, from today")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import a statement" })).toHaveAttribute(
      "href",
      "/bank",
    );
  });
});
