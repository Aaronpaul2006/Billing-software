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
  BOQ: "BOQ progress (one project)",
  PROJECTS: "Project margins",
  STATEMENT: "Statement of account",
};

/** Made from a client's page, not from the Exports form (it needs the client). */
export const FORM_KINDS = (Object.keys(KIND_LABELS) as Export["kind"][]).filter(
  (k) => k !== "STATEMENT",
);

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

type ExportRequest = components["schemas"]["ExportRequest"];

/** How often a file being made is looked at again (tests set 0). */
export const polling = { delayMs: 1500, attempts: 40 };

/**
 * Ask for a file, wait while the worker makes it, then download it. Throws
 * with a readable message if it failed or is still not ready after a minute
 * (it then stays on the Exports page for 7 days).
 */
export async function makeAndDownload(body: ExportRequest, key: string): Promise<void> {
  let x = unwrap(await api.POST("/api/v1/exports", { body, headers: { "Idempotency-Key": key } }));
  for (let i = 0; x.status === "PENDING" && i < polling.attempts; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, polling.delayMs));
    x = unwrap(
      await api.GET("/api/v1/exports/{export_id}", { params: { path: { export_id: x.id } } }),
    );
  }
  if (x.status === "FAILED") throw new Error(x.error ?? "The file could not be made.");
  if (x.status === "PENDING") {
    throw new Error("The file is still being made. It will be on the Exports page shortly.");
  }
  await downloadExport(x.id);
}
