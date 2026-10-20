/**
 * The typed API client. Types come from backend/openapi.json
 * (`npm run gen:api` writes src/api/schema.d.ts).
 *
 * authFetch adds the access token, and on `401 token_expired` refreshes the
 * session once and retries. Errors become ApiError with the problem body.
 */

import createClient from "openapi-fetch";

import { getAccessToken, refreshSession } from "@/auth/session";

import { ApiError, isProblem, networkProblem } from "./problem";
import type { paths } from "./schema";

const RETRY_CODES = new Set(["token_expired", "invalid_token"]);

function isAuthEndpoint(url: string): boolean {
  return new URL(url, window.location.origin).pathname.startsWith("/api/v1/auth/");
}

/**
 * Set the token on the request itself (allowed for script-made requests).
 * Not `new Request(request, { headers: new Headers(request.headers) })`:
 * copying Headers like that lost every header in the test environment
 * (Idempotency-Key included), so nothing is copied.
 */
function withToken(request: Request): Request {
  const token = getAccessToken();
  if (token) request.headers.set("Authorization", `Bearer ${token}`);
  return request;
}

async function problemCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.clone().json();
    return isProblem(body) ? body.code : null;
  } catch {
    return null;
  }
}

export async function authFetch(request: Request): Promise<Response> {
  const retry = request.clone();
  const response = await fetch(withToken(request));
  if (response.status !== 401 || isAuthEndpoint(request.url)) return response;
  const code = await problemCode(response);
  if (!code || !RETRY_CODES.has(code)) return response;
  const session = await refreshSession();
  return session ? fetch(withToken(retry)) : response;
}

export const api = createClient<paths>({
  baseUrl: window.location.origin, // same origin as the app (Vite proxies /api in dev)
  credentials: "same-origin",
  headers: { Accept: "application/json" },
  // django-filter "in" lookups read one comma-separated value: doc_type=A,B
  querySerializer: { array: { style: "form", explode: false } },
  fetch: authFetch,
});

/**
 * Unwrap an openapi-fetch result: the data, or throw ApiError.
 * Usage: `const doc = unwrap(await api.GET("/api/v1/documents/{id}", ...))`.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const problem = isProblem(result.error)
      ? result.error
      : networkProblem(`Unexpected response ${result.response.status}.`);
    throw new ApiError(problem);
  }
  return result.data as T;
}

/** A fresh Idempotency-Key. Keep one per user action and resend it on retry. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
