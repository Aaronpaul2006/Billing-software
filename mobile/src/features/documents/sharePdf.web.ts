import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";

import type { ShareOutcome } from "./sharePdf";

/** In a browser: open the PDF (a 5-minute link) in a new tab instead of the share sheet. */
export async function shareDocumentPdf(documentId: string): Promise<ShareOutcome> {
  const { data, error, response } = await api.GET("/api/v1/documents/{document_id}/pdf", {
    params: { path: { document_id: documentId }, query: { as: "link" } },
  });
  const link = unwrap({ data, error, response });
  if (response.status === 202 || typeof link !== "object" || !("url" in link)) return "preparing";
  window.open(link.url, "_blank", "noopener");
  return "shared";
}

export function shareErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status !== 0) return error.message;
  return "Could not open the PDF. Check your connection and try again.";
}
