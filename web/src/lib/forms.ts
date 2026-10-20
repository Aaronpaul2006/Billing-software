import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "@/api/problem";

/** "lines[0].rate" (API) -> "lines.0.rate" (form path). */
export function formPath(field: string): string {
  return field.replace(/\[(\d+)\]/g, ".$1");
}

function known(path: string, fields: readonly string[]): boolean {
  // "lines.*" covers every "lines.<n>.<field>"
  return fields.some((f) => (f.endsWith(".*") ? path.startsWith(f.slice(0, -1)) : f === path));
}

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
    const path = e.field ? formPath(e.field) : null;
    if (path && known(path, fields)) {
      setError(path as Path<T>, { type: e.code, message: e.message });
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
