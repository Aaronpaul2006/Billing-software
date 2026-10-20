import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

describe("reports", () => {
  it("GST summary for a month, B2B / B2C by rate", async () => {
    const periods: (string | null)[] = [];
    server.use(
      http.get(`${API}/reports/gst-summary`, ({ request }) => {
        periods.push(new URL(request.url).searchParams.get("period"));
        return HttpResponse.json({
          period: "2026-10",
          results: [
            {
              supply: "B2B",
              gst_rate: "18.00",
              document_count: 2,
              taxable_value: "282200.00",
              cgst: "25398.00",
              sgst: "25398.00",
              igst: "0.00",
              cess: "0.00",
            },
          ],
          totals: {
            taxable_value: "282200.00",
            cgst: "25398.00",
            sgst: "25398.00",
            igst: "0.00",
            cess: "0.00",
          },
        });
      }),
    );
    renderSignedIn("/reports");
    const row = (await screen.findByText("B2B")).closest("tr") as HTMLElement;
    expect(within(row).getByText("18 %")).toBeInTheDocument();
    expect(within(row).getAllByText("₹25,398.00")).toHaveLength(2);
    expect(periods[0]).toMatch(/^\d{4}-\d{2}$/); // this month by default
  });

  it("project margins, TDS status and billing by month", async () => {
    server.use(
      http.get(`${API}/reports/gst-summary`, () =>
        HttpResponse.json({
          period: "2026-10",
          results: [],
          totals: { taxable_value: "0.00", cgst: "0.00", sgst: "0.00", igst: "0.00", cess: "0.00" },
        }),
      ),
      http.get(`${API}/reports/projects`, () =>
        HttpResponse.json({
          results: [
            {
              project_id: "p1",
              code: "VILLA-1",
              name: "Villa",
              contract_value: "4500000.00",
              billed_taxable: "282200.00",
              retention_held: "14450.00",
              retention_released: "0.00",
              tds_deducted: "2890.00",
              advance_recovered: "0.00",
              outstanding: "23680.00",
              cost: "300000.00",
              margin: "-17800.00",
            },
          ],
        }),
      ),
      http.get(`${API}/reports/tds-reconciliation`, () =>
        HttpResponse.json({
          fy_start_year: 2026,
          results: [
            {
              party_id: "c1",
              display_name: "Skyline Developers",
              quarter: 3,
              deductor_tans: "BLRS12345E",
              bill_count: 2,
              taxable_value: "578000.00",
              expected: "5780.00",
              certificate_count: 1,
              certified: "5000.00",
              difference: "-780.00",
              status: "SHORT",
              certificate_due: "2027-02-15",
              overdue: true,
            },
          ],
          totals: { expected: "5780.00", certified: "5000.00", difference: "-780.00" },
        }),
      ),
      http.get(`${API}/reports/billing-by-month`, () =>
        HttpResponse.json({
          results: [
            {
              month: "2026-09-01",
              book: "GST",
              document_count: 1,
              taxable_value: "0",
              tax: "0",
              billed: "100000.00",
            },
            {
              month: "2026-10-01",
              book: "GST",
              document_count: 3,
              taxable_value: "0",
              tax: "0",
              billed: "400000.00",
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/reports");
    await user.click(await screen.findByRole("button", { name: "Project margins" }));
    const margin = await screen.findByText("-₹17,800.00");
    expect(margin).toHaveClass("text-destructive");

    await user.click(screen.getByRole("button", { name: "TDS reconciliation" }));
    expect(await screen.findByText("Short")).toBeInTheDocument();
    expect(screen.getByText("overdue since 2027-02-15")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Billing by month" }));
    const rows = await screen.findAllByText(/^(Sept?|Oct) 2026$/);
    expect(rows).toHaveLength(2);
    const bars = document.querySelectorAll<HTMLElement>("td div.bg-primary");
    await waitFor(() => {
      expect([...bars].map((b) => b.style.width)).toEqual(["25%", "100%"]);
    });
  });
});
