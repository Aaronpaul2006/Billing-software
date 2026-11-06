/** Bill fixtures shared by the document tests. */
import type { components } from "@/api/schema";

import { API, http, HttpResponse, server } from "./server";

type Document = components["schemas"]["Document"];

export const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";
export const PROJECT = "0192f5c4-0000-7000-8000-0000000000p1";
export const DOC = "0192f5c4-0000-7000-8000-0000000000d1";

export const TOTALS = {
  subtotal: "289000.00",
  cgst: "26010.00",
  sgst: "26010.00",
  igst: "0.00",
  cess: "0.00",
  round_off: "0.00",
  grand_total: "341020.00",
  retention: "14450.00",
  income_tax_tds: "2890.00",
  gst_tds: "0.00",
  advance_recovery: "0.00",
  net_receivable: "323680.00",
  amount_settled: "0.00",
  outstanding: "323680.00",
};

export function doc(overrides: Partial<Document> = {}): Document {
  return {
    id: DOC,
    version: 1,
    doc_type: "TAX_INVOICE",
    status: "DRAFT",
    doc_number: null,
    doc_date: "2026-10-19",
    fy_start_year: 2026,
    due_date: null,
    valid_until: null,
    gst_registration_id: "r1",
    party_id: CLIENT,
    party_name: "Skyline Developers",
    project_id: PROJECT,
    project_name: "Villa at Kakkanad",
    place_of_supply: "32",
    supply_type: "INTRA_STATE",
    supply_category: "REGULAR",
    lut: false,
    reverse_charge: false,
    is_gst_document: true,
    round_to_rupee: false,
    is_ra_bill: false,
    ra_sequence: null,
    totals: TOTALS,
    issued_at: null,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    notes: null,
    terms: null,
    approval_requested_at: null,
    approved_at: null,
    approved_by_name: null,
    approval_holds: false,
    lines: [
      {
        line_no: 1,
        catalog_item_id: null,
        catalog_variant_id: null,
        boq_item_id: "b1",
        description: "RCC M25 for slabs",
        sac_hsn: "995453",
        unit: "cum",
        quantity: "42.500",
        prev_cumulative_qty: null,
        up_to_date_qty: null,
        measurements: [],
        rate: "6800.00",
        discount_amount: "0.00",
        discount_pct: null,
        taxable_value: "289000.00",
        gst_rate: "18.00",
        cgst_amount: "26010.00",
        sgst_amount: "26010.00",
        igst_amount: "0.00",
        cess_amount: "0.00",
        line_total: "341020.00",
      },
    ],
    ...overrides,
  };
}

export function useDoc(d: Document) {
  server.use(http.get(`${API}/documents/${d.id}`, () => HttpResponse.json(d)));
}
