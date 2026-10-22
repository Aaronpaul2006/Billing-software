import { fireEvent, screen } from "@testing-library/react-native";

import { formatRange, periodRange } from "@/lib/periods";
import { EMPTY_RECEIVABLES, EMPTY_SUMMARY, json, on, problem } from "@/test/api";
import { renderSignedIn } from "@/test/render";

function totals(billed: string) {
  return {
    billed,
    taxable: billed,
    tax: "0.00",
    collected: "50000.00",
    expenses: "12000.00",
    outstanding: "323680.00",
  };
}

function client(name: string, total: string, over90 = "0.00") {
  return {
    party_id: `p-${name}`,
    display_name: name,
    document_count: 2,
    not_due: "0.00",
    days_1_30: "0.00",
    days_31_60: "0.00",
    days_61_90: "0.00",
    days_90_plus: over90,
    total,
  };
}

describe("dashboard", () => {
  it("shows the period's totals against the previous period, and who owes the most", async () => {
    const asked: string[] = [];
    on("GET", "/reports/summary", (request) => {
      const q = new URL(request.url).searchParams;
      asked.push(`${q.get("book") ?? ""} ${q.get("from") ?? ""}..${q.get("to") ?? ""}`);
      return json({
        ...EMPTY_SUMMARY,
        current: totals("344196.00"),
        previous: totals("120000.00"),
      });
    });
    on("GET", "/reports/receivables", () =>
      json({
        // Not sorted by the server: the app shows the largest first, compared exactly.
        results: [
          client("Small Co", "9999.99"),
          client("Skyline Developers", "323680.00", "100000.00"),
          client("Kochi Metro", "100000.00"),
          client("A", "1.00"),
          client("B", "2.00"),
          client("C", "3.00"),
        ],
        totals: { ...EMPTY_RECEIVABLES.totals, total: "433686.99" },
      }),
    );
    await renderSignedIn("/");
    expect(await screen.findByText("₹3,44,196.00")).toBeTruthy();
    expect(screen.getByText("Previous period: ₹1,20,000.00")).toBeTruthy();
    expect(screen.getAllByText("₹3,23,680.00")).toHaveLength(2); // outstanding, and Skyline
    expect(screen.getByText("Today, all periods")).toBeTruthy();

    const names = (await screen.findAllByText(/^(Skyline|Kochi|Small|A|B|C)( |$)/)).map(
      (n) => n.props.children as string,
    );
    expect(names).toEqual(["Skyline Developers", "Kochi Metro", "Small Co", "C", "B"]);
    expect(screen.getByText("₹1,00,000.00 over 90 days")).toBeTruthy();
    expect(screen.getByText("All 6 clients")).toBeTruthy();
    expect(screen.getByText("₹4,33,686.99")).toBeTruthy();

    await fireEvent.press(screen.getByRole("radio", { name: "Last financial year" }));
    await fireEvent.press(screen.getByRole("radio", { name: "GST" }));
    const { from, to } = periodRange("last_fy", new Date());
    expect(await screen.findByText(formatRange(from, to))).toBeTruthy();
    expect(asked.at(-1)).toBe(`GST ${from}..${to}`);
  });

  it("explains a role without reports", async () => {
    on("GET", "/reports/summary", () => problem(403, "permission_denied"));
    on("GET", "/reports/receivables", () => problem(403, "permission_denied"));
    await renderSignedIn("/", { role: "SITE_ENGINEER" });
    expect(await screen.findAllByRole("alert")).toHaveLength(2); // summary and receivables
    expect(screen.getAllByText("Your role does not have access to this.")).toHaveLength(2);
  });
});
