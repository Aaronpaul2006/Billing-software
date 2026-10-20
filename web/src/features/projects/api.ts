import { useQuery } from "@tanstack/react-query";
import { useOutletContext } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type Project = components["schemas"]["Project"];
export type ProjectStatus = Project["status"];
export type BoqItem = components["schemas"]["BoqItem"];

export const STATUS_LABELS: Record<ProjectStatus, string> = {
  PLANNED: "Planned",
  ACTIVE: "Active",
  ON_HOLD: "On hold",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
};

export function projectKey(id: string) {
  return ["project", id] as const;
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKey(id),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } }),
      ),
  });
}

/** Active GST registrations of the company, default first. */
export function useRegistrations() {
  return useQuery({
    queryKey: ["gst-registrations", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/gst-registrations", {
          params: { query: { is_active: true, limit: 100 } },
        }),
      ).results.sort((a, b) => Number(b.is_default) - Number(a.is_default)),
    staleTime: 5 * 60_000,
  });
}

/** The project of the /projects/:projectId page, for its tabs. */
export function useProjectOutlet(): { project: Project } {
  return useOutletContext<{ project: Project }>();
}
