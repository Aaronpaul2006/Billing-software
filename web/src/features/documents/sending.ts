import { formatInr } from "@/lib/money";
import { formatDate } from "@/lib/dates";

import { DOC_TYPE_LABELS } from "./api";
import type { Document } from "./api";

export type PrintCopy = "original" | "duplicate" | "triplicate";

/** Roles that may email a bill out (backend: documents.issue). */
export const MAY_EMAIL: ReadonlySet<string> = new Set(["OWNER", "ADMIN", "ACCOUNTANT"]);

/** Indian numbers for wa.me: digits only, with the 91 country code. */
export function whatsappNumber(phone: string | null | undefined): string {
  const digits = (phone ?? "").replace(/\D/g, "");
  if (digits.length === 10) return `91${digits}`;
  if (digits.length === 11 && digits.startsWith("0")) return `91${digits.slice(1)}`;
  return digits;
}

const day = (iso: string) => formatDate(iso);

/** The message staff send with the PDF (they attach the file themselves). */
export function whatsappMessage(doc: Document, upiId: string | null | undefined): string {
  const title = DOC_TYPE_LABELS[doc.doc_type];
  const asksPayment = doc.doc_type !== "CREDIT_NOTE" && doc.doc_type !== "QUOTATION";
  const lines = [
    `Dear ${doc.party_name},`,
    `${title} ${doc.doc_number ?? ""} dated ${day(doc.doc_date)} for ${formatInr(doc.totals.net_receivable)}${
      asksPayment && doc.due_date ? `, due on ${day(doc.due_date)}` : ""
    }.`,
    ...(asksPayment && upiId ? [`Pay by UPI: ${upiId}`] : []),
    "The PDF is attached.",
  ];
  return lines.join("\n");
}

export function whatsappLink(phone: string | null | undefined, text: string): string {
  return `https://wa.me/${whatsappNumber(phone)}?text=${encodeURIComponent(text)}`;
}

export function pdfName(doc: Document, copy: PrintCopy): string {
  const number = (doc.doc_number ?? "draft").replace(/\//g, "-");
  return `${doc.doc_type.toLowerCase()}-${number}-${copy}.pdf`;
}
