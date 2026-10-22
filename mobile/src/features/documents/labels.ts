// Labels kept in step with web/src/features/documents/api.ts.

import type { components } from "@/api/schema";
import type { Tone } from "@/components/list";
import { compareMoney } from "@/lib/money";
import { isoDate } from "@/lib/periods";

export type DocType = components["schemas"]["DocTypeEnum"];
export type DocStatus = components["schemas"]["DocumentStatusEnum"];
type Listed = components["schemas"]["DocumentList"];

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  TAX_INVOICE: "Tax invoice",
  BILL_OF_SUPPLY: "Bill of supply",
  PROFORMA: "Proforma invoice",
  QUOTATION: "Quotation",
  CREDIT_NOTE: "Credit note",
  DEBIT_NOTE: "Debit note",
};

export const STATUS_LABELS: Record<DocStatus, string> = {
  DRAFT: "Draft",
  ISSUED: "Issued",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
  CANCELLED: "Cancelled",
};

/** Settled by payments / credit notes: invoices, bills of supply and debit notes. */
export const RECEIVABLE_TYPES: readonly DocType[] = ["TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE"];

export function documentTitle(
  d: Pick<Listed, "doc_type" | "doc_number" | "is_ra_bill" | "ra_sequence">,
): string {
  const type = DOC_TYPE_LABELS[d.doc_type];
  const ra = d.is_ra_bill && d.ra_sequence ? ` · RA bill ${String(d.ra_sequence)}` : "";
  return `${type} ${d.doc_number ?? "(draft)"}${ra}`;
}

/** "Paid", "Part paid", "Overdue"... for an issued receivable; else the status. */
export function standing(
  d: Pick<Listed, "doc_type" | "status" | "due_date" | "totals">,
  today = new Date(),
): { text: string; tone: Tone } {
  if (d.status !== "ISSUED" || !RECEIVABLE_TYPES.includes(d.doc_type)) {
    const tone: Tone =
      d.status === "DRAFT" ? "warn" : d.status === "CANCELLED" ? "muted" : "default";
    return { text: STATUS_LABELS[d.status], tone };
  }
  const { outstanding, net_receivable } = d.totals;
  if (compareMoney(outstanding, "0") !== 1) return { text: "Paid", tone: "good" };
  if (d.due_date && d.due_date < isoDate(today)) return { text: "Overdue", tone: "danger" };
  return compareMoney(outstanding, net_receivable) === -1
    ? { text: "Part paid", tone: "warn" }
    : { text: "Unpaid", tone: "default" };
}

/** "2026-10-19" -> "19 Oct 2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y = 0, m = 1, d = 1] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
