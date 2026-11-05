import type { components } from "@/api/schema";

export type Template = components["schemas"]["Template"];

/** Kinds of document a template can start (not credit / debit notes). */
export const TEMPLATE_TYPES: ReadonlySet<string> = new Set([
  "QUOTATION",
  "PROFORMA",
  "TAX_INVOICE",
  "BILL_OF_SUPPLY",
]);

// backend: masters.edit saves / edits templates; documents.draft uses them
