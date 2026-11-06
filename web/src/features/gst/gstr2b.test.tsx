import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const STEEL = "32AAACK1234M1Z8";

function ret(over: Record<string, unknown> = {}) {
  return {
    id: "g1",
    gst_registration_id: "reg1",
    gstin: "32AABCD1234E1Z5",
    period: "2026-10-01",
    generated_on: "2026-11-14",
    file_name: "returns_102026_R2B.json",
    doc_count: 5,
    uploaded_by: "Aaron Paul",
    created_at: "",
    ...over,
  };
}

const RECON = {
  gst_return: ret(),
  summary: {
    matched: 2,
    amounts_differ: 1,
    not_in_books: 2,
    not_in_2b: 1,
    itc_in_2b: "15120.00",
    itc_matched: "12600.00",
    itc_not_in_books: "900.00",
    itc_at_risk: "1440.00",
  },
  rows: [
    {
      status: "AMOUNTS_DIFFER",
      supplier_gstin: STEEL,
      supplier_name: "Kerala Steel Traders",
      portal: {
        id: "l2",
        section: "B2B",
        doc_type: "INVOICE",
        doc_number: "KST/102",
        original_number: null,
        doc_date: "2026-10-28",
        taxable_value: "10000.00",
        tax: "1800.00",
        itc_available: true,
        itc_reason: null,
        reverse_charge: false,
      },
      books: {
        kind: "VENDOR_BILL",
        id: "b2",
        number: "KST/102",
        doc_date: "2026-10-28",
        taxable_value: "10000.00",
        tax: "1700.00",
        itc_eligible: true,
      },
      taxable_difference: "0.00",
      tax_difference: "100.00",
      note: "",
    },
    {
      status: "NOT_IN_2B",
      supplier_gstin: STEEL,
      supplier_name: "Kerala Steel Traders",
      portal: null,
      books: {
        kind: "VENDOR_BILL",
        id: "b5",
        number: "KST/105",
        doc_date: "2026-10-30",
        taxable_value: "8000.00",
        tax: "1440.00",
        itc_eligible: true,
      },
      taxable_difference: "0.00",
      tax_difference: "0.00",
      note: "",
    },
  ],
};

describe("GSTR-2B check (Part B)", () => {
  it("shows the month against the books, by status", async () => {
    server.use(
      http.get(`${API}/gstr2b-returns`, () =>
        HttpResponse.json({ results: [ret()], next_cursor: null }),
      ),
      http.get(`${API}/gstr2b-returns/g1/reconciliation`, () => HttpResponse.json(RECON)),
    );
    const user = userEvent.setup();
    renderSignedIn("/gstr2b");
    expect(await screen.findByRole("heading", { name: "Oct 2026" })).toBeInTheDocument();
    expect(screen.getByText("At risk").parentElement).toHaveTextContent("₹1,440.00");
    const table = screen.getByRole("table", { name: "GSTR-2B against our books" });
    expect(within(table).getByRole("link", { name: "KST/105" })).toHaveAttribute(
      "href",
      "/vendor-bills/b5",
    );
    expect(within(table).getByText(/₹100.00/)).toBeInTheDocument(); // more tax in the 2B
    await user.selectOptions(screen.getByLabelText("Show"), "NOT_IN_2B");
    expect(within(table).queryByText("KST/102")).not.toBeInTheDocument();
    expect(within(table).getByText("KST/105")).toBeInTheDocument();
  });

  it("says why an upload is refused", async () => {
    server.use(
      http.get(`${API}/gstr2b-returns`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.post(`${API}/gstr2b-returns`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Invalid input",
            status: 422,
            code: "validation_error",
            errors: [
              {
                field: "file",
                code: "other_gstin",
                message: "This GSTR-2B is for GSTIN 32AAACK1234M1Z8, which is not one of yours.",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/gstr2b");
    expect(await screen.findByText(/No GSTR-2B uploaded yet/)).toBeInTheDocument();
    await user.upload(
      screen.getByLabelText("Upload a GSTR-2B (JSON)"),
      new File(["{}"], "2b.json", { type: "application/json" }),
    );
    expect(await screen.findByText(/which is not one of yours/)).toBeInTheDocument();
  });
});
