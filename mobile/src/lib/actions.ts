import { randomUUID } from "expo-crypto";

/** A fresh Idempotency-Key. Keep one per user action and resend it on retry. */
export function newIdempotencyKey(): string {
  return randomUUID();
}

/** The If-Match header for a resource at `version` (ETag "v3"). */
export function ifMatch(version: number): string {
  return `"v${String(version)}"`;
}

// Who may do what (backend/apps/core/permissions.py); the server checks again.
const RECORD_PAYMENTS = new Set(["OWNER", "ADMIN", "ACCOUNTANT"]);
const ISSUE_DOCUMENTS = new Set(["OWNER", "ADMIN", "ACCOUNTANT"]);

export function canRecordPayments(role: string): boolean {
  return RECORD_PAYMENTS.has(role);
}

export function canIssueDocuments(role: string): boolean {
  return ISSUE_DOCUMENTS.has(role);
}
