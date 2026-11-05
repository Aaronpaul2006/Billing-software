/**
 * Who may do what, as on the server (backend/apps/core/permissions.py ACTIONS;
 * docs/01-architecture.md §3). The web app only uses it to hide what a role
 * cannot use: the server checks every request itself.
 */

export type Role = "OWNER" | "ADMIN" | "ACCOUNTANT" | "SITE_ENGINEER" | "VIEWER" | "CLIENT";

export type Action =
  | "tenant.settings"
  | "members.manage"
  | "masters.edit"
  | "documents.draft"
  | "documents.issue"
  | "payments.record"
  | "expenses.record"
  | "reports.view"
  | "audit.view";

const ACTIONS: Record<Action, ReadonlySet<string>> = {
  "tenant.settings": new Set(["OWNER", "ADMIN"]),
  "members.manage": new Set(["OWNER", "ADMIN"]),
  "masters.edit": new Set(["OWNER", "ADMIN", "ACCOUNTANT"]),
  "documents.draft": new Set(["OWNER", "ADMIN", "ACCOUNTANT", "SITE_ENGINEER"]),
  "documents.issue": new Set(["OWNER", "ADMIN", "ACCOUNTANT"]),
  "payments.record": new Set(["OWNER", "ADMIN", "ACCOUNTANT"]),
  "expenses.record": new Set(["OWNER", "ADMIN", "ACCOUNTANT", "SITE_ENGINEER"]),
  "reports.view": new Set(["OWNER", "ADMIN", "ACCOUNTANT", "VIEWER"]),
  "audit.view": new Set(["OWNER", "ADMIN"]),
};

export function can(role: string | null | undefined, action: Action): boolean {
  return role ? ACTIONS[action].has(role) : false;
}
