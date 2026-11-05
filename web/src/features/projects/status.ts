import type { Status } from "@/components/status";

/** A project's badge (D.3). */
const PROJECT_STATUS: Record<string, Status> = {
  PLANNED: "planned",
  ACTIVE: "active",
  ON_HOLD: "on_hold",
  COMPLETED: "completed",
  CANCELLED: "cancelled",
};

export function projectStatus(status: string): Status {
  return PROJECT_STATUS[status] ?? "active";
}
