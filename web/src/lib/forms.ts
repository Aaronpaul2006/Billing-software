import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "@/api/problem";

/**
 * Put a 422's field errors on the form fields they name ("billing_address.pincode"
 * is a form path too). Returns a message for everything else (other fields,
 * conflicts, network errors), for an alert above the form.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly string[],
): string | null {
  if (!(error instanceof ApiError)) return "Could not reach the server. Check your connection.";
  const leftovers: string[] = [];
  for (const e of error.problem.errors ?? []) {
    if (e.field && fields.includes(e.field)) {
      setError(e.field as Path<T>, { type: e.code, message: e.message });
    } else {
      leftovers.push(e.field ? `${e.field}: ${e.message}` : e.message);
    }
  }
  if (!error.problem.errors?.length) return error.message;
  return leftovers.length ? leftovers.join(" ") : null;
}

/** "" -> null for optional text inputs, so the API stores no value rather than "". */
export function blankToNull(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed === "" ? null : trimmed;
}

/** The If-Match header for a resource at `version` (ETag "v3"). */
export function ifMatch(version: number): string {
  return `"v${version}"`;
}
