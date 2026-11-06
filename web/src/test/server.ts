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
  http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: 0 })),
  http.get(`${API}/tenant`, () =>
    HttpResponse.json({
      id: "t1",
      legal_name: "Nair Constructions",
      trade_name: null,
      pan: null,
      status: "ACTIVE",
      plan: "FREE",
      timezone: "Asia/Kolkata",
      approval_limit: null,
      version: 1,
      created_at: "",
      updated_at: "",
    }),
  ),
  http.get(`${API}/notifications`, () => HttpResponse.json({ results: [], next_cursor: null })),
  http.get(`${API}/email-invitations`, () => HttpResponse.json({ results: [] })),
  http.get(`${API}/documents/:id/reminders`, () => HttpResponse.json({ results: [] })),
  http.get(`${API}/documents/:id/photos`, () => HttpResponse.json({ results: [] })),
  http.get(`${API}/portal/documents/:id/photos`, () => HttpResponse.json({ results: [] })),
  // The bill screen's lookups for a chosen client (B.4): no earlier bill, nothing owed.
  http.get(`${API}/documents`, () => HttpResponse.json({ results: [], next_cursor: null })),
  http.get(`${API}/parties/:id/statement`, () => problem(403, "permission_denied")),
  http.get(`${API}/parties/:id/last-rates`, () => HttpResponse.json({ results: [] })),
  http.get(`${API}/parties/:id`, () => problem(404, "not_found")),
  // A business that has finished setting up: no checklist on the first page.
  http.get(`${API}/tenant/setup`, () =>
    HttpResponse.json({
      gst_registration: true,
      number_series: true,
      client: true,
      project: true,
      first_bill: true,
      team: true,
      complete: true,
    }),
  ),
  // The final review before issuing: nothing to say.
  http.get(`${API}/documents/:id/review`, () => HttpResponse.json({ warnings: [] })),
  // Print settings never saved: the defaults.
  http.get(`${API}/tenant/print-settings`, () =>
    HttpResponse.json(
      {
        layout: "DETAILED",
        logo_attachment_id: null,
        signature_attachment_id: null,
        bank_account_name: null,
        bank_name: null,
        bank_account_number: null,
        bank_ifsc: null,
        bank_branch: null,
        upi_id: null,
        default_terms: null,
        version: 1,
      },
      { headers: { ETag: '"v1"' } },
    ),
  ),
);

export { http, HttpResponse };
