/** API objects for tests, typed against the schema so they stay complete. */

import type { components } from "@/api/schema";

type S = components["schemas"];

export const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";
export const PROJECT = "0192f5c4-0000-7000-8000-0000000000d1";

/** The API doc's RA bill: ₹2,89,000 + 18 % GST, retention 5 %, TDS 1 %. */
export function totals(over: Partial<S["Totals"]> = {}): S["Totals"] {
  return {
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
    ...over,
  };
}

export function listed(over: Partial<S["DocumentList"]> = {}): S["DocumentList"] {
  return {
    id: "d1",
    version: 2,
    doc_type: "TAX_INVOICE",
    status: "ISSUED",
    doc_number: "INV/0001",
    doc_date: "2026-10-19",
    fy_start_year: 2026,
    due_date: "2099-11-18",
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
    is_ra_bill: true,
    ra_sequence: 1,
    totals: totals(),
    issued_at: "2026-10-19T10:00:00Z",
    created_at: "2026-10-19T09:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    ...over,
  };
}

export function line(over: Partial<S["LineOut"]> = {}): S["LineOut"] {
  return {
    line_no: 1,
    catalog_item_id: null,
    boq_item_id: "b1",
    description: "RCC M25",
    sac_hsn: "995411",
    unit: "cum",
    quantity: "42.500",
    prev_cumulative_qty: "0.000",
    up_to_date_qty: "42.500",
    rate: "6800.00",
    discount_amount: "0.00",
    taxable_value: "289000.00",
    gst_rate: "18.00",
    cgst_amount: "26010.00",
    sgst_amount: "26010.00",
    igst_amount: "0.00",
    cess_amount: "0.00",
    line_total: "341020.00",
    ...over,
  };
}

export function document(over: Partial<S["Document"]> = {}): S["Document"] {
  return { ...listed(), notes: null, terms: null, lines: [line()], ...over };
}

export function payment(over: Partial<S["Payment"]> = {}): S["Payment"] {
  return {
    id: "pay1",
    version: 1,
    party_id: CLIENT,
    party_name: "Skyline Developers",
    project_id: null,
    project_name: null,
    payment_date: "2026-10-21",
    amount: "200000.00",
    mode: "UPI",
    reference: "UTR123",
    notes: null,
    status: "RECORDED",
    allocated: "150000.00",
    unallocated: "50000.00",
    allocations: [
      {
        id: "a1",
        document_id: "d1",
        doc_number: "INV/0001",
        retention_release_id: null,
        payment_id: "pay1",
        credit_note_id: null,
        amount: "150000.00",
        created_at: "2026-10-21T10:00:00Z",
      },
    ],
    voided_at: null,
    void_reason: null,
    created_at: "2026-10-21T10:00:00Z",
    updated_at: "2026-10-21T10:00:00Z",
    ...over,
  };
}

export function projectReport(over: Partial<S["ProjectReport"]> = {}): S["ProjectReport"] {
  return {
    project_id: PROJECT,
    code: "VILLA-1",
    name: "Villa at Kakkanad",
    contract_value: "1140000.00",
    billed_taxable: "289000.00",
    retention_held: "14450.00",
    retention_released: "0.00",
    tds_deducted: "2890.00",
    advance_recovered: "0.00",
    outstanding: "323680.00",
    cost: "310000.00",
    margin: "-21000.00",
    ...over,
  };
}
