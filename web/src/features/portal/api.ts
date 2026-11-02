import { queryOptions } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type PortalDocument = components["schemas"]["PortalDocument"];
export type PortalDocumentDetail = components["schemas"]["PortalDocumentDetail"];
export type PortalPayment = components["schemas"]["PortalPayment"];
export type PortalProject = components["schemas"]["PortalProject"];
export type Statement = components["schemas"]["Statement"];

export const portalMeQuery = queryOptions({
  queryKey: ["portal", "me"],
  queryFn: async () => unwrap(await api.GET("/api/v1/portal/me")),
  staleTime: 5 * 60_000,
});

export function portalDocumentsQuery(
  docTypes: readonly string[] = [],
  status: readonly string[] = [],
) {
  return queryOptions({
    queryKey: ["portal", "documents", docTypes, status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/documents", {
          params: {
            query: {
              ...(docTypes.length ? { doc_type: [...docTypes] } : {}),
              ...(status.length ? { status: [...status] } : {}),
            },
          },
        }),
      ),
  });
}

export function portalDocumentKey(id: string) {
  return ["portal", "document", id] as const;
}

export function portalDocumentQuery(id: string) {
  return queryOptions({
    queryKey: portalDocumentKey(id),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/documents/{document_id}", {
          params: { path: { document_id: id } },
        }),
      ),
  });
}

export const portalPaymentsQuery = queryOptions({
  queryKey: ["portal", "payments"],
  queryFn: async () => unwrap(await api.GET("/api/v1/portal/payments")),
});

export function portalStatementQuery(from: string, to: string) {
  return queryOptions({
    queryKey: ["portal", "statement", from, to],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/portal/statement", { params: { query: { from, to } } })),
  });
}

export const portalProjectsQuery = queryOptions({
  queryKey: ["portal", "projects"],
  queryFn: async () => unwrap(await api.GET("/api/v1/portal/projects")),
});

export function portalBoqQuery(projectId: string) {
  return queryOptions({
    queryKey: ["portal", "boq", projectId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/projects/{project_id}/boq-progress", {
          params: { path: { project_id: projectId } },
        }),
      ),
  });
}

/** Bills the client owes on (quotations and notes are not bills). */
export const BILL_TYPES = ["TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE"] as const;
