import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type { components } from "@/api/schema";

export const API = `${window.location.origin}/api/v1`;

type Tokens = components["schemas"]["Tokens"];
type Me = components["schemas"]["Me"];

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

export function problem(status: number, code: string, detail = code) {
  return HttpResponse.json(
    { type: `/errors/${code}`, title: code, status, code, detail, request_id: null },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

/** Defaults: nobody is signed in (no refresh cookie); no pending invitations. */
export const server = setupServer(
  http.post(`${API}/auth/token/refresh`, () => problem(401, "invalid_refresh_token")),
  http.get(`${API}/invitations`, () => HttpResponse.json({ results: [] })),
);

export { http, HttpResponse };
