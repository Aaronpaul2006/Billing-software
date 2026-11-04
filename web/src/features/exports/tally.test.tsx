import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const LEDGERS = {
  sales_ledger: "Sales",
  cgst_ledger: "Output CGST",
  sgst_ledger: "Output SGST",
  igst_ledger: "Output IGST",
  cess_ledger: "Output Cess",
  round_off_ledger: "Round Off",
  tds_ledger: "TDS Receivable",
  gst_tds_ledger: "GST TDS Receivable",
  retention_ledger: "Retention Receivable",
  advance_ledger: "Client Advances",
  bank_ledger: "Bank Account",
  cash_ledger: "Cash",
  version: 1,
};

describe("Tally export", () => {
  it("asks for vouchers as XML for the chosen dates", async () => {
    let body: unknown = null;
    server.use(
      http.get(`${API}/exports`, () => HttpResponse.json({ results: [] })),
      http.post(`${API}/exports`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "x1", status: "PENDING" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/exports");
    const form = await screen.findByRole("form", { name: "New export" });
    await user.selectOptions(within(form).getByLabelText("What"), "TALLY");
    expect(within(form).queryByLabelText("File")).toBeNull(); // always XML
    expect(within(form).getByRole("link", { name: "Settings, Tally export" })).toHaveAttribute(
      "href",
      "/settings/tally",
    );
    await user.clear(within(form).getByLabelText("From"));
    await user.type(within(form).getByLabelText("From"), "2026-10-01");
    await user.clear(within(form).getByLabelText("To"));
    await user.type(within(form).getByLabelText("To"), "2026-10-31");
    await user.click(within(form).getByRole("button", { name: "Make the file" }));
    await waitFor(() => {
      expect(body).toEqual({
        kind: "TALLY",
        format: "XML",
        params: { from: "2026-10-01", to: "2026-10-31" },
      });
    });
  });

  it("saves the ledger names as they are in Tally", async () => {
    let sent: Record<string, string> | null = null;
    let match: string | null = null;
    server.use(
      http.get(`${API}/tenant/tally-settings`, () => HttpResponse.json(LEDGERS)),
      http.patch(`${API}/tenant/tally-settings`, async ({ request }) => {
        sent = (await request.json()) as Record<string, string>;
        match = request.headers.get("If-Match");
        return HttpResponse.json({ ...LEDGERS, ...sent, version: 2 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/tally");
    const sales = await screen.findByLabelText("Sales");
    await user.clear(sales);
    await user.type(sales, "Works Contract Sales 18%");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/next Tally export uses these names/)).toBeInTheDocument();
    expect(match).toBe('"v1"');
    expect(sent).toMatchObject({ sales_ledger: "Works Contract Sales 18%", cash_ledger: "Cash" });
  });
});
