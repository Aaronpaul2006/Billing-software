import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type Export = components["schemas"]["Export"];

export const KIND_LABELS: Record<Export["kind"], string> = {
  DOCUMENTS: "Invoice register",
  PAYMENTS: "Payments",
  EXPENSES: "Expenses",
  RECEIVABLES: "Receivables (as of today)",
  GSTR1: "GSTR-1",
};

export function fileSize(bytes: number | null): string {
  if (bytes === null) return "";
  return bytes < 1024 * 1024
    ? `${String(Math.ceil(bytes / 1024))} KB`
    : `${(bytes / 1048576).toFixed(1)} MB`;
}

/** Leaving the page for a download (replaced in tests: jsdom cannot navigate). */
export const browser = {
  open(url: string) {
    window.location.assign(url);
  },
};

/** Ask for a fresh link at click time: the one in the list lasts 5 minutes. */
export async function downloadExport(exportId: string): Promise<void> {
  const fresh = unwrap(
    await api.GET("/api/v1/exports/{export_id}", { params: { path: { export_id: exportId } } }),
  );
  if (fresh.download_url) browser.open(fresh.download_url);
}

/** Your recent exports; while one is being made, looks again every 2 seconds. */
export function useExports() {
  return useQuery({
    queryKey: ["exports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/exports")).results,
    refetchInterval: (query) =>
      query.state.data?.some((x) => x.status === "PENDING") ? 2000 : false,
  });
}
