import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { answerConfirm } from "@/test/confirm";
import { renderApp, renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, me, problem, server, tokens } from "@/test/server";

type PortalDocumentDetail = components["schemas"]["PortalDocumentDetail"];
type Totals = components["schemas"]["Totals"];
type PortalUser = components["schemas"]["PortalUser"];

const CLIENT = { role: "CLIENT" as const };

function totals(over: Partial<Totals> = {}): Totals {
  return {
    subtotal: "100000.00",
    cgst: "9000.00",
    sgst: "9000.00",
    igst: "0.00",
    cess: "0.00",
    round_off: "0.00",
    grand_total: "118000.00",
    retention: "0.00",
    income_tax_tds: "0.00",
    gst_tds: "0.00",
    advance_recovery: "0.00",
    net_receivable: "118000.00",
    amount_settled: "0.00",
    outstanding: "118000.00",
    ...over,
  };
}

function quote(over: Partial<PortalDocumentDetail> = {}): PortalDocumentDetail {
  return {
    id: "q1",
    version: 1,
    doc_type: "QUOTATION",
    status: "ISSUED",
    doc_number: "QT/0007",
    doc_date: "2026-10-28",
    due_date: null,
    valid_until: "2026-11-30",
    project_id: null,
    project_name: "Villa",
    is_gst_document: false,
    is_ra_bill: false,
    ra_sequence: null,
    totals: totals(),
    issued_at: "2026-10-28T10:00:00Z",
    place_of_supply: "32",
    terms: "Valid for 30 days.",
    lines: [
      {
        line_no: 1,
        boq_item_id: null,
        description: "RCC work",
        sac_hsn: "9954",
        unit: "cum",
        quantity: "10.000",
        prev_cumulative_qty: null,
        up_to_date_qty: null,
        measurements: [],
        rate: "10000.00",
        discount_amount: "0.00",
        taxable_value: "100000.00",
        gst_rate: "18.00",
        cgst_amount: "9000.00",
        sgst_amount: "9000.00",
        igst_amount: "0.00",
        cess_amount: "0.00",
        line_total: "118000.00",
      },
    ],
    ...over,
  };
}

function portalApi() {
  server.use(
    http.get(`${API}/portal/me`, () =>
      HttpResponse.json({
        business: { legal_name: "Nair Constructions", trade_name: null },
        client: { id: "c1", display_name: "Skyline Developers", gstin: null },
      }),
    ),
    http.get(`${API}/portal/statement`, () =>
      HttpResponse.json({
        party: { id: "c1", display_name: "Skyline Developers", gstin: null },
        from: "2026-04-01",
        to: "2026-11-02",
        opening_balance: "0.00",
        entries: [],
        total_debit: "323680.00",
        total_credit: "100000.00",
        closing_balance: "223680.00",
      }),
    ),
    http.get(`${API}/portal/documents`, ({ request }) => {
      const types = new URL(request.url).searchParams.get("doc_type");
      return HttpResponse.json({
        results: types === "QUOTATION" ? [quote()] : [],
        next_cursor: null,
      });
    }),
  );
}

describe("client portal", () => {
  it("a client signs in with the emailed code and lands on the portal", async () => {
    const user = userEvent.setup();
    portalApi();
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({ mfa_required: true, mfa_token: "mfa-1", mfa_method: "email" }),
      ),
      http.post(`${API}/auth/mfa/verify`, async ({ request }) => {
        const body = (await request.json()) as { code?: string };
        return body.code === "246810"
          ? HttpResponse.json(tokens(CLIENT))
          : problem(401, "invalid_mfa_code");
      }),
      http.get(`${API}/me`, () => HttpResponse.json(me())),
    );
    const router = renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "anna@skyline.in");
    await user.type(screen.getByLabelText("Password"), "a long passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/We emailed you a 6-digit code/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Code"), "recovery-code");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Enter the 6-digit code from the email.")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Code"));
    await user.type(screen.getByLabelText("Code"), "111111");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/Use the latest email we sent/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Code"));
    await user.type(screen.getByLabelText("Code"), "246810");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/portal");
    expect(await screen.findByText("₹2,23,680.00")).toBeInTheDocument();
    expect(screen.getByText("Nair Constructions")).toBeInTheDocument();
    expect(await screen.findByText(/QT\/0007/)).toBeInTheDocument();
  });

  it("keeps clients out of the business's pages, and staff out of the portal", async () => {
    portalApi();
    const router = renderSignedIn("/documents", CLIENT);
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/portal");
  });

  it("sends staff away from the portal", async () => {
    server.use(
      http.get(`${API}/reports/summary`, () => problem(500, "x")),
      http.get(`${API}/reports/receivables`, () => problem(500, "x")),
    );
    const router = renderSignedIn("/portal");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("accepts a quotation with If-Match", async () => {
    const user = userEvent.setup();
    portalApi();
    let ifMatch: string | null = null;
    server.use(
      http.get(`${API}/portal/documents/q1`, () => HttpResponse.json(quote())),
      http.post(`${API}/portal/documents/q1/accept`, ({ request }) => {
        ifMatch = request.headers.get("If-Match");
        return HttpResponse.json(quote({ status: "ACCEPTED", version: 2 }));
      }),
    );
    renderSignedIn("/portal/bills/q1", CLIENT);
    expect(await screen.findByRole("heading", { name: "Quotation QT/0007" })).toBeInTheDocument();
    expect(screen.getByText("RCC work")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await answerConfirm(user, "Accept quotation");
    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    expect(ifMatch).toBe('"v1"');
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  });

  it("explains an expired quotation", async () => {
    const user = userEvent.setup();
    portalApi();
    server.use(
      http.get(`${API}/portal/documents/q1`, () => HttpResponse.json(quote())),
      http.post(`${API}/portal/documents/q1/decline`, () =>
        problem(409, "quotation_expired", "This quotation has expired."),
      ),
    );
    renderSignedIn("/portal/bills/q1", CLIENT);
    await user.click(await screen.findByRole("button", { name: "Decline" }));
    await answerConfirm(user, "Decline quotation");
    expect(await screen.findByText(/Ask us for a new one/)).toBeInTheDocument();
  });
});

describe("portal access on the client page", () => {
  const PARTY = "0192f5c4-0000-7000-8000-0000000000c1";

  function partyApi() {
    server.use(
      http.get(`${API}/parties/${PARTY}`, () =>
        HttpResponse.json({
          id: PARTY,
          display_name: "Skyline Developers",
          legal_name: null,
          is_customer: true,
          is_vendor: false,
          gst_treatment: "UNREGISTERED",
          gstin: null,
          pan: null,
          state_code: "32",
          state_name: "Kerala",
          billing_address: null,
          email: null,
          phone: null,
          reminders_enabled: true,
          is_active: true,
          version: 1,
          created_at: "2026-10-19T10:00:00Z",
          updated_at: "2026-10-19T10:00:00Z",
        }),
      ),
    );
  }

  it("lists, invites and explains a conflict", async () => {
    const user = userEvent.setup();
    partyApi();
    let rows: PortalUser[] = [
      {
        id: "m1",
        kind: "MEMBER",
        email: "anna@skyline.in",
        full_name: "Anna Kurian",
        status: "ACTIVE",
        created_at: "2026-11-01T10:00:00Z",
        expires_at: null,
      },
    ];
    let invited: unknown = null;
    server.use(
      http.get(`${API}/parties/${PARTY}/portal-users`, () => HttpResponse.json({ results: rows })),
      http.post(`${API}/parties/${PARTY}/portal-users`, async ({ request }) => {
        invited = await request.json();
        if ((invited as { email: string }).email === "staff@nair.in") {
          return problem(409, "already_member");
        }
        const row: PortalUser = {
          id: "i1",
          kind: "EMAIL_INVITATION",
          email: "ravi@skyline.in",
          full_name: null,
          status: "PENDING",
          created_at: "2026-11-02T10:00:00Z",
          expires_at: "2026-11-09T10:00:00Z",
        };
        rows = [...rows, row];
        return HttpResponse.json(row, { status: 201 });
      }),
    );
    renderSignedIn(`/parties/${PARTY}`);
    const list = await screen.findByRole("list", { name: "Portal users" });
    expect(within(list).getByText("Anna Kurian")).toBeInTheDocument();
    expect(within(list).getByText("Active")).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Invite to the client portal" });
    await user.type(within(form).getByLabelText("Email"), "ravi@skyline.in");
    await user.click(within(form).getByRole("button", { name: "Invite" }));
    expect(await screen.findByText("ravi@skyline.in")).toBeInTheDocument();
    expect(screen.getByText("Email sent")).toBeInTheDocument();
    expect(invited).toEqual({ email: "ravi@skyline.in" });

    await user.type(within(form).getByLabelText("Email"), "staff@nair.in");
    await user.click(within(form).getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/is a member of your business/)).toBeInTheDocument();
  });

  it("is not shown to accountants", async () => {
    partyApi();
    renderSignedIn(`/parties/${PARTY}`, { role: "ACCOUNTANT" });
    expect(await screen.findByDisplayValue("Skyline Developers")).toBeInTheDocument();
    expect(screen.queryByText("Client portal")).not.toBeInTheDocument();
  });
});
