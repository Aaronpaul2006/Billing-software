import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const VENDOR = "0192f5c4-0000-7000-8000-0000000000e1";
const PROJECT = "0192f5c4-0000-7000-8000-0000000000f1";

function item(over: Record<string, unknown> = {}) {
  return {
    id: "i1",
    boq_item_id: null,
    boq_item_code: null,
    item_code: "1",
    description: "Brickwork in CM 1:6",
    unit: "cum",
    sac_hsn: null,
    qty: "100.000",
    rate: "4000.00",
    gst_rate: "18.00",
    amount: "400000.00",
    billed_qty: "40.000",
    balance_qty: "60.000",
    ...over,
  };
}

function order(over: Record<string, unknown> = {}) {
  return {
    id: "w1",
    version: 1,
    project_id: PROJECT,
    project_code: "VILLA-1",
    project_name: "Villa",
    vendor_party_id: VENDOR,
    vendor_name: "Ravi Kumar",
    wo_number: "WO/VILLA-1/01",
    wo_date: "2026-10-01",
    title: "Brickwork and plastering",
    terms: null,
    retention_pct: "5.00",
    tds_section: "194C",
    tds_rate: "1.00",
    status: "OPEN",
    value: "550000.00",
    billed: "160000.00",
    retention_held: "8000.00",
    paid: "0.00",
    ra_count: 1,
    created_at: "",
    updated_at: "",
    items: [
      item(),
      item({
        id: "i2",
        item_code: "2",
        description: "Plastering 12 mm",
        unit: "sqm",
        qty: "500.000",
        rate: "300.00",
        amount: "150000.00",
        billed_qty: "0.000",
        balance_qty: "500.000",
      }),
    ],
    ra_bills: [
      {
        id: "b1",
        ra_number: 1,
        bill_number: "RK/RA-1",
        bill_date: "2026-10-20",
        taxable_value: "160000.00",
        retention_amount: "8000.00",
        net_payable: "179200.00",
        amount_paid: "0.00",
        status: "RECORDED",
      },
    ],
    ...over,
  };
}

const page = (results: object[]) => HttpResponse.json({ results, next_cursor: null });

describe("work orders and RA bills (payables part 2)", () => {
  it("lists work orders with how much is billed", async () => {
    server.use(http.get(`${API}/work-orders`, () => page([order()])));
    renderSignedIn("/work-orders");
    const table = await screen.findByRole("table", { name: "Work orders" });
    const link = await within(table).findByRole("link", { name: "WO/VILLA-1/01" });
    const row = link.closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Ravi Kumar");
    expect(row).toHaveTextContent("₹1,60,000.00 · 29 %");
  });

  it("creates a work order with an item from the client's BOQ", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/projects`, () => page([{ id: PROJECT, code: "VILLA-1", name: "Villa" }])),
      http.get(`${API}/projects/${PROJECT}/boq-items`, () =>
        page([
          {
            id: "q1",
            item_code: "2.1",
            description: "Brick masonry in CM 1:6",
            unit: "cum",
            contract_qty: "120.000",
            rate: "6200.00",
            gst_rate: "18.00",
          },
        ]),
      ),
      http.get(`${API}/parties`, () =>
        page([{ id: VENDOR, display_name: "Ravi Kumar", gstin: null }]),
      ),
      http.post(`${API}/work-orders`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(order(), { status: 201 });
      }),
      http.get(`${API}/work-orders/w1`, () => HttpResponse.json(order())),
    );
    const user = userEvent.setup();
    renderSignedIn("/work-orders/new");
    await screen.findByRole("option", { name: "VILLA-1 · Villa" });
    await user.selectOptions(screen.getByLabelText("Project"), PROJECT);
    await user.type(screen.getByLabelText("Subcontractor"), "ravi");
    await user.click(await screen.findByRole("button", { name: /Ravi Kumar/ }));
    await user.type(screen.getByLabelText("Work let"), "Brickwork");
    await user.selectOptions(await screen.findByLabelText("Add from the client's BOQ"), "q1");
    const first = screen.getByRole("listitem", { name: "Item 1" });
    expect(within(first).getByLabelText("Code")).toHaveValue("2.1");
    expect(within(first).getByLabelText("Quantity")).toHaveValue("120");
    await user.type(within(first).getByLabelText("Rate (₹)"), "4000");
    expect(screen.getByRole("status")).toHaveTextContent("Work order value ₹4,80,000.00");
    await user.click(screen.getByRole("button", { name: "Save work order" }));
    await waitFor(() => {
      expect(sent).not.toBeNull();
    });
    expect(sent).toMatchObject({
      project_id: PROJECT,
      vendor_party_id: VENDOR,
      title: "Brickwork",
      retention_pct: "5",
      tds_section: "194C",
      items: [
        {
          boq_item_id: "q1",
          item_code: "2.1",
          unit: "cum",
          qty: "120",
          rate: "4000",
          gst_rate: "18",
        },
      ],
    });
  });

  it("records an RA bill: this bill's quantities, what we pay, never past the work order", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/work-orders/w1`, () => HttpResponse.json(order())),
      http.post(`${API}/work-orders/w1/ra-bills`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "b2" }, { status: 201 });
      }),
      http.get(`${API}/vendor-bills/b2`, () => HttpResponse.json({})),
    );
    const user = userEvent.setup();
    renderSignedIn("/work-orders/w1/ra-bills/new");
    expect(
      await screen.findByRole("heading", { name: "Quantities: RA bill 2" }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Their bill number"), "RK/RA-2");
    const brick = screen.getByLabelText("This bill, item 1 (cum)");
    await user.type(brick, "60.5");
    expect(screen.getByText("At most 60")).toBeInTheDocument();
    await user.clear(brick);
    await user.type(brick, "40");
    await user.type(screen.getByLabelText("This bill, item 2 (sqm)"), "200");
    // 160000 + 60000 = 220000; GST 39600; TDS 2200; retention 11000
    const summary = screen.getByLabelText("What we pay");
    expect(summary).toHaveTextContent("₹2,20,000.00");
    expect(summary).toHaveTextContent("₹39,600.00");
    expect(summary).toHaveTextContent("₹2,200.00");
    expect(summary).toHaveTextContent("₹11,000.00");
    expect(summary).toHaveTextContent("₹2,46,400.00");
    await user.click(screen.getByRole("button", { name: "Save RA bill" }));
    await waitFor(() => {
      expect(sent).not.toBeNull();
    });
    expect(sent).toMatchObject({
      bill_number: "RK/RA-2",
      lines: [
        { work_order_item_id: "i1", qty: "40" },
        { work_order_item_id: "i2", qty: "200" },
      ],
    });
  });

  it("shows a work order's items, bills and actions", async () => {
    server.use(http.get(`${API}/work-orders/w1`, () => HttpResponse.json(order())));
    renderSignedIn("/work-orders/w1");
    expect(await screen.findByRole("link", { name: "Record RA bill" })).toHaveAttribute(
      "href",
      "/work-orders/w1/ra-bills/new",
    );
    const items = screen.getByRole("table", { name: "Work order items" });
    expect(within(items).getByText("60 cum")).toBeInTheDocument(); // left
    const bills = screen.getByRole("table", { name: "RA bills" });
    expect(within(bills).getByRole("link", { name: "RA 1 · RK/RA-1" })).toHaveAttribute(
      "href",
      "/vendor-bills/b1",
    );
  });

  it("an RA bill's page shows its quantities, retention and work order; it is not edited", async () => {
    server.use(
      http.get(`${API}/vendor-bills/b1`, () =>
        HttpResponse.json({
          id: "b1",
          version: 1,
          vendor_party_id: VENDOR,
          vendor_name: "Ravi Kumar",
          project_id: PROJECT,
          project_name: "Villa",
          bill_number: "RK/RA-1",
          bill_date: "2026-10-20",
          due_date: null,
          category: "SUBCONTRACT",
          description: "RA bill 1 · Brickwork and plastering",
          taxable_value: "160000.00",
          gst_amount: "28800.00",
          total_amount: "188800.00",
          itc_eligible: false,
          tds_section: "194C",
          tds_rate: "1.00",
          tds_amount: "1600.00",
          net_payable: "179200.00",
          work_order_id: "w1",
          wo_number: "WO/VILLA-1/01",
          ra_number: 1,
          retention_amount: "8000.00",
          lines: [
            {
              id: "l1",
              work_order_item_id: "i1",
              item_code: "1",
              description: "Brickwork in CM 1:6",
              unit: "cum",
              qty: "40.000",
              rate: "4000.00",
              amount: "160000.00",
              gst_rate: "18.00",
            },
          ],
          amount_paid: "0.00",
          outstanding: "179200.00",
          attachment_id: null,
          notes: null,
          status: "RECORDED",
          voided_at: null,
          void_reason: null,
          created_at: "",
          updated_at: "",
        }),
      ),
    );
    renderSignedIn("/vendor-bills/b1");
    expect(await screen.findByRole("link", { name: "WO/VILLA-1/01" })).toHaveAttribute(
      "href",
      "/work-orders/w1",
    );
    const lines = screen.getByRole("table", { name: "Quantities on this bill" });
    expect(within(lines).getByText("40 cum")).toBeInTheDocument();
    expect(screen.getByText("Less retention held")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Void…" })).toBeEnabled();
  });
});
