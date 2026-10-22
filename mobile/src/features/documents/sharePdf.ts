import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";

export type ShareOutcome = "shared" | "preparing" | "unavailable";

/**
 * Download an issued document's PDF (a 5-minute link from the API) into the
 * cache and open the share sheet (WhatsApp, email...). "preparing": the worker
 * has not made it yet (the API answers 202); try again in a moment.
 */
export async function shareDocumentPdf(
  documentId: string,
  fileName: string,
): Promise<ShareOutcome> {
  if (!(await Sharing.isAvailableAsync())) return "unavailable";
  const { data, error, response } = await api.GET("/api/v1/documents/{document_id}/pdf", {
    params: { path: { document_id: documentId }, query: { as: "link" } },
  });
  const link = unwrap({ data, error, response });
  // 202 while the worker makes it; anything but the link counts as not ready.
  if (response.status === 202 || typeof link !== "object" || !("url" in link)) return "preparing";
  const target = new File(Paths.cache, `${fileName.replace(/[^\w.-]+/g, "-")}.pdf`);
  const file = await File.downloadFileAsync(link.url, target, { idempotent: true });
  await Sharing.shareAsync(file.uri, {
    mimeType: "application/pdf",
    UTI: "com.adobe.pdf",
    dialogTitle: fileName,
  });
  return "shared";
}

export function shareErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status !== 0) return error.message;
  return "Could not download the PDF. Check your connection and try again.";
}
