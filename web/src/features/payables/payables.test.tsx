import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const VENDOR = "0192f5c4-0000-7000-8000-0000000000e1";

function bill(over: Record<string, unknown> = {}) {
  return {
    id: "b1",
    version: 1,
    vendor_party_id: VENDOR,
    vendor_name: "Ravi Kumar",
    project_id: null,
    project_name: null,
    bill_number: "RK/101",
    bill_date: "2026-10-01",
    due_date: "2026-10-15",
    category: "SUBCONTRACT",
    description: "Brickwork",
    taxable_value: "50000.00",
    gst_amount: "9000.00",
    total_amount: "59000.00",
    itc_eligible: false,
    tds_section: "194C",
    tds_rate: "1.00",
    tds_amount: "500.00",
    net_payable: "58500.00",
    work_order_id: null,
    wo_number: null,
    ra_number: null,
    retention_amount: "0.00",
    lines: [],
    amount_paid: "0.00",
    outstanding: "58500.00",
    attachment_id: null,
    notes: null,
    status: "RECORDED",
    voided_at: null,
    void_reason: null,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

const page = (results: object[]) => HttpResponse.json({ results, next_cursor: null });

describe("payables (Part B)", () => {
  it("lists vendor bills with what we owe", async () => {
    server.use(
      http.get(`${API}/vendor-bills`, () =>
        page([
          bill(),
          bill({ id: "b2", bill_number: "RK/102", amount_paid: "58500.00", outstanding: "0.00" }),
        ]),
      ),
      http.get(`${API}/reports/payables`, () =>
        HttpResponse.json({
          as_of: "2026-11-06",
          results: [
            {
              party_id: VENDOR,
              display_name: "Ravi Kumar",
              bill_count: 1,
              not_due: "0.00",
              days_1_30: "58500.00",
              days_31_60: "0.00",
              days_61_90: "0.00",
              days_90_plus: "0.00",
              total: "58500.00",
            },
          ],
          totals: {
            party_id: "00000000-0000-0000-0000-000000000000",
            display_name: "All vendors",
            bill_count: 1,
            not_due: "0.00",
            days_1_30: "58500.00",
            days_31_60: "0.00",
            days_61_90: "0.00",
            days_90_plus: "0.00",
            total: "58500.00",
          },
        }),
      ),
    );
    renderSignedIn("/vendor-bills");
    const owe = await screen.findByRole("heading", { name: "What we owe" });
    const card = owe.closest("[data-slot=card]") as HTMLElement;
    expect(card).toHaveTextContent("₹58,500.00");
    const table = await screen.findByRole("table", { name: "Vendor bills" });
    const first = (await within(table).findAllByRole("link", { name: "Ravi Kumar" }))[0]?.closest(
      "tr",
    );
    expect(first).toHaveTextContent("RK/101");
    expect(first).toHaveTextContent("Overdue");
    expect(within(table).getByText("Total of 2 shown").closest("tr")).toHaveTextContent(
      "₹58,500.00",
    );
  });

  it("records a vendor bill, using the suggested TDS", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/parties`, () =>
        page([{ id: VENDOR, display_name: "Ravi Kumar", gstin: null }]),
      ),
      http.get(`${API}/projects`, () => page([])),
      http.get(`${API}/vendor-bills/tds-suggestion`, () =>
        HttpResponse.json({
          section: "194C",
          rate: "1.00",
          amount: "500.00",
          reason:
            "194C (payments to contractors and subcontractors): 1 %, because the vendor is an individual or HUF (from the PAN).",
          year_total: "0.00",
        }),
      ),
      http.post(`${API}/vendor-bills`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(bill(), { status: 201 });
      }),
      http.get(`${API}/vendor-bills/b1`, () => HttpResponse.json(bill())),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/vendor-bills/new");
    await user.type(await screen.findByLabelText("Vendor"), "ravi");
    await user.click(await screen.findByRole("button", { name: /Ravi Kumar/ }));
    await user.type(screen.getByLabelText("Their bill number"), "RK/101");
    await user.type(screen.getByLabelText("What it is for"), "Brickwork");
    await user.type(screen.getByLabelText("Amount before GST (₹)"), "50,000");
    await user.clear(screen.getByLabelText("GST (₹)"));
    await user.type(screen.getByLabelText("GST (₹)"), "9000");
    const hint = await screen.findByText(/Suggested TDS: 194C at 1.00 % = ₹500.00/);
    await user.click(
      within(hint.closest("[role=status]") as HTMLElement).getByRole("button", {
        name: "Use this",
      }),
    );
    expect(screen.getByLabelText("TDS section (empty: no TDS)")).toHaveValue("194C");
    expect(screen.getByLabelText("TDS rate (%)")).toHaveValue("1.00");
    expect(screen.getByText("Bill total ₹59,000.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Record bill" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/vendor-bills/b1");
    });
    expect(sent).toMatchObject({
      vendor_party_id: VENDOR,
      bill_number: "RK/101",
      category: "SUBCONTRACT",
      taxable_value: "50000",
      gst_amount: "9000",
      tds_section: "194C",
      tds_rate: "1.00",
    });
  });

  it("pays a vendor, oldest bill first", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/vendor-bills`, () =>
        page([
          bill(),
          bill({
            id: "b2",
            bill_number: "RK/102",
            bill_date: "2026-10-20",
            outstanding: "20000.00",
          }),
        ]),
      ),
      http.post(`${API}/vendor-payments`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "vp1" }, { status: 201 });
      }),
      http.get(`${API}/vendor-payments/vp1`, () =>
        HttpResponse.json({
          id: "vp1",
          version: 1,
          vendor_party_id: VENDOR,
          vendor_name: "Ravi Kumar",
          project_id: null,
          project_name: null,
          payment_date: "2026-11-06",
          amount: "70000.00",
          mode: "UPI",
          reference: null,
          notes: null,
          status: "RECORDED",
          unallocated: "0.00",
          allocations: [],
          voided_at: null,
          void_reason: null,
          created_at: "",
          updated_at: "",
        }),
      ),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/vendor-payments/new?vendor=${VENDOR}&name=Ravi%20Kumar`);
    expect(await screen.findByDisplayValue("Ravi Kumar")).toBeInTheDocument();
    const bills = await screen.findByRole("list", { name: "Bills to pay" });
    await user.type(screen.getByLabelText("Amount paid (₹)"), "70000");
    expect(within(bills).getByLabelText("Pay against RK/101")).toHaveValue("58500.00");
    expect(within(bills).getByLabelText("Pay against RK/102")).toHaveValue("11500.00");
    await user.selectOptions(screen.getByLabelText("How"), "UPI");
    await user.click(screen.getByRole("button", { name: "Record payment" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/vendor-payments/vp1");
    });
    expect(sent).toMatchObject({
      vendor_party_id: VENDOR,
      amount: "70000",
      mode: "UPI",
      allocations: [
        { vendor_bill_id: "b1", amount: "58500.00" },
        { vendor_bill_id: "b2", amount: "11500.00" },
      ],
    });
  });

  it("a paid bill cannot be edited or voided from its page", async () => {
    server.use(
      http.get(`${API}/vendor-bills/b1`, () =>
        HttpResponse.json(bill({ amount_paid: "1000.00", outstanding: "57500.00" })),
      ),
    );
    renderSignedIn("/vendor-bills/b1");
    const actions = await screen.findByRole("group", { name: "Actions" });
    expect(within(actions).queryByRole("link", { name: "Edit" })).toBeNull();
    expect(within(actions).getByRole("button", { name: "Void…" })).toBeDisabled();
    expect(within(actions).getByRole("link", { name: "Pay this vendor" })).toBeInTheDocument();
  });
});
