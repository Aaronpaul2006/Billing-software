/**
 * A small stand-in for the API in tests (MSW 3 is ESM-only and does not load
 * under Jest here). Handlers match "METHOD /path" under /api/v1, newest first,
 * so a test can override a default. A request nobody handles fails the test.
 */

import type { components } from "@/api/schema";
import { API_URL } from "@/config";

type Tokens = components["schemas"]["Tokens"];
type Me = components["schemas"]["Me"];

export const API = `${API_URL}/api/v1`;

export type Handler = (
  request: Request,
  params: Record<string, string>,
) => Response | Promise<Response>;

interface Route {
  method: string;
  pattern: RegExp;
  keys: string[];
  handler: Handler;
}

let routes: Route[] = [];
let unhandled: string[] = [];

/** Handle `method path` ("/projects/:id" style) until the test ends. */
export function on(method: string, path: string, handler: Handler): void {
  const keys: string[] = [];
  const source = path
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/:(\w+)/g, (_, key: string) => {
      keys.push(key);
      return "([^/]+)";
    });
  routes.unshift({ method, pattern: new RegExp(`^${source}$`), keys, handler });
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function problem(status: number, code: string, detail = code): Response {
  return new Response(
    JSON.stringify({
      type: `/errors/${code}`,
      title: code,
      status,
      code,
      detail,
      request_id: null,
    }),
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

async function stubFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = input instanceof Request ? input : new Request(input, init);
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/v1/, "");
  for (const route of routes) {
    if (route.method !== request.method) continue;
    const match = route.pattern.exec(path);
    if (!match) continue;
    const params = Object.fromEntries(route.keys.map((k, i) => [k, match[i + 1] ?? ""]));
    return route.handler(request, params);
  }
  unhandled.push(`${request.method} ${url.pathname}${url.search}`);
  throw new TypeError(`Unhandled request: ${request.method} ${url.pathname}`);
}

export function installApi(): void {
  routes = [];
  unhandled = [];
  globalThis.fetch = jest.fn(stubFetch) as typeof fetch;
}

/** Fails the test when the app called the API in a way no handler expected. */
export function assertAllHandled(): void {
  const missed = unhandled;
  unhandled = [];
  if (missed.length) throw new Error(`Unhandled API requests:\n${missed.join("\n")}`);
}

export const TENANT_A = "0192f5c4-0000-7000-8000-00000000000a";
export const TENANT_B = "0192f5c4-0000-7000-8000-00000000000b";

export function tokens(overrides: Partial<Tokens> = {}): Tokens {
  return {
    token_type: "Bearer",
    access_token: "access-1",
    expires_in: 600,
    session_id: "0192f5c4-0000-7000-8000-000000000001",
    user_id: "0192f5c4-0000-7000-8000-000000000002",
    tenant_id: TENANT_A,
    role: "OWNER",
    mfa_enrollment_required: false,
    tenants: [
      { id: TENANT_A, legal_name: "Nair Constructions", role: "OWNER" },
      { id: TENANT_B, legal_name: "Nair Infra", role: "ACCOUNTANT" },
    ],
    refresh_token: "refresh-1",
    ...overrides,
  };
}

export function me(overrides: Partial<Me> = {}): Me {
  return {
    id: "0192f5c4-0000-7000-8000-000000000002",
    email: "asha@nairconstructions.in",
    email_verified: true,
    full_name: "Asha Nair",
    phone: null,
    mfa_enabled: true,
    mfa_enrollment_required: false,
    tenant_id: TENANT_A,
    role: "OWNER",
    memberships: [
      { tenant_id: TENANT_A, legal_name: "Nair Constructions", role: "OWNER" },
      { tenant_id: TENANT_B, legal_name: "Nair Infra", role: "ACCOUNTANT" },
    ],
    ...overrides,
  };
}

const ZERO = {
  billed: "0.00",
  taxable: "0.00",
  tax: "0.00",
  collected: "0.00",
  expenses: "0.00",
  outstanding: "0.00",
};

export const EMPTY_SUMMARY = {
  book: "ALL",
  period: {},
  previous_period: {},
  current: ZERO,
  previous: ZERO,
};

export const EMPTY_RECEIVABLES = {
  results: [],
  totals: {
    party_id: "",
    display_name: "",
    document_count: 0,
    not_due: "0.00",
    days_1_30: "0.00",
    days_31_60: "0.00",
    days_61_90: "0.00",
    days_90_plus: "0.00",
    total: "0.00",
  },
};

/** A quiet dashboard: nothing billed, nothing outstanding. */
export function emptyDashboard(): void {
  on("GET", "/reports/summary", () => json(EMPTY_SUMMARY));
  on("GET", "/reports/receivables", () => json(EMPTY_RECEIVABLES));
}
