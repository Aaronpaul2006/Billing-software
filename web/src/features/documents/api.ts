import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type Document = components["schemas"]["Document"];
export type DocType = components["schemas"]["DocTypeEnum"];
export type DraftableType = components["schemas"]["DraftableDocTypeEnum"];
export type DocStatus = components["schemas"]["DocumentStatusEnum"];
export type Totals = components["schemas"]["Totals"];
export type LineOut = components["schemas"]["LineOut"];

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  TAX_INVOICE: "Tax invoice",
  BILL_OF_SUPPLY: "Bill of supply",
  PROFORMA: "Proforma invoice",
  QUOTATION: "Quotation",
  CREDIT_NOTE: "Credit note",
  DEBIT_NOTE: "Debit note",
};

export const DRAFTABLE: readonly DraftableType[] = [
  "TAX_INVOICE",
  "BILL_OF_SUPPLY",
  "PROFORMA",
  "QUOTATION",
];

export const STATUS_LABELS: Record<DocStatus, string> = {
  DRAFT: "Draft",
  ISSUED: "Issued",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
  CANCELLED: "Cancelled",
};

export function statusVariant(
  status: DocStatus,
): "default" | "secondary" | "outline" | "destructive" {
  switch (status) {
    case "ISSUED":
    case "ACCEPTED":
      return "default";
    case "DRAFT":
      return "outline";
    case "CANCELLED":
    case "DECLINED":
      return "secondary";
  }
}

/** Settled by payments / credit notes: invoices, bills of supply and debit notes. */
export const RECEIVABLE_TYPES: ReadonlySet<DocType> = new Set([
  "TAX_INVOICE",
  "BILL_OF_SUPPLY",
  "DEBIT_NOTE",
]);

export function documentKey(id: string) {
  return ["document", id] as const;
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: documentKey(id),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}", {
          params: { path: { document_id: id } },
        }),
      ),
  });
}

export function documentTitle(
  d: Pick<Document, "doc_type" | "doc_number" | "is_ra_bill" | "ra_sequence">,
): string {
  const type = DOC_TYPE_LABELS[d.doc_type];
  const ra = d.is_ra_bill && d.ra_sequence ? ` · RA bill ${String(d.ra_sequence)}` : "";
  return `${type} ${d.doc_number ?? "(draft)"}${ra}`;
}
