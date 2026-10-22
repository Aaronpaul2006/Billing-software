/** RFC 9457 problem details, as every API error is returned (docs/02-api-design.md §1). */
export interface FieldError {
  field: string | null;
  code: string;
  message: string;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  errors?: FieldError[];
  request_id?: string | null;
  current?: unknown; // 412 stale_version: the resource as it is now
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }

  get code(): string {
    return this.problem.code;
  }
}

export function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    "code" in value &&
    typeof (value as { code: unknown }).code === "string"
  );
}

/** Field errors keyed by field path ("lines[0].rate"); "" for form-level errors. */
export function fieldErrors(problem: Problem): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of problem.errors ?? []) {
    out[e.field ?? ""] ??= e.message;
  }
  if (!problem.errors?.length) out[""] = problem.detail ?? problem.title;
  return out;
}

/** A problem for when the server could not be reached or sent something else. */
export function networkProblem(detail: string): Problem {
  return { type: "about:blank", title: "Network error", status: 0, code: "network_error", detail };
}
