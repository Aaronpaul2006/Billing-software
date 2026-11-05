import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { answerConfirm } from "@/test/confirm";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

type Payment = components["schemas"]["Payment"];

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";
const PAY = "0192f5c4-0000-7000-8000-0000000000a1";

function payment(overrides: Partial<Payment> = {}): Payment {
  return {
    id: PAY,
    version: 1,
    party_id: CLIENT,
    party_name: "Skyline Developers",
    project_id: null,
    project_name: null,
    payment_date: "2026-10-25",
    amount: "330000.00",
    mode: "BANK_TRANSFER",
    reference: "UTR123",
    notes: null,
    status: "RECORDED",
    allocated: "323680.00",
    unallocated: "6320.00",
    allocations: [
      {
        id: "al1",
        document_id: "d1",
        doc_number: "INV/0001",
        retention_release_id: null,
        payment_id: PAY,
        credit_note_id: null,
        amount: "323680.00",
        created_at: "2026-10-25T10:00:00Z",
      },
    ],
    voided_at: null,
    void_reason: null,
    created_at: "2026-10-25T10:00:00Z",
    updated_at: "2026-10-25T10:00:00Z",
    ...overrides,
  };
}

function openDocument(id: string, number: string, date: string, outstanding: string) {
  return {
    id,
    doc_number: number,
    doc_type: "TAX_INVOICE",
    doc_date: date,
    totals: { outstanding },
  };
}

function openItems() {
  server.use(
    http.get(`${API}/documents`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      expect(q.get("payment_state")).toBe("OPEN");
      expect(q.get("party_id")).toBe(CLIENT);
      expect(q.get("ordering")).toBe("doc_date,doc_number");
      return HttpResponse.json({
        results: [
          openDocument("d1", "INV/0001", "2026-10-19", "323680.00"),
          openDocument("d2", "INV/0002", "2026-10-20", "10600.00"),
        ],
        next_cursor: null,
      });
    }),
    http.get(`${API}/retention-releases`, () =>
      HttpResponse.json({
        results: [
          {
            id: "r1",
            reference: "RET/1",
            release_date: "2026-11-05",
            outstanding: "20000.00",
            status: "RELEASED",
          },
        ],
        next_cursor: null,
      }),
    ),
  );
}

describe("payments", () => {
  it("lists payments with the client and what is still unallocated", async () => {
    server.use(
      http.get(`${API}/payments`, () =>
        HttpResponse.json({ results: [payment()], next_cursor: null }),
      ),
    );
    renderSignedIn("/payments");
    // the client's name opens the payment
    const row = (await screen.findByRole("link", { name: "Skyline Developers" })).closest(
      "tr",
    ) as HTMLElement;
    expect(row).toHaveTextContent("25 Oct 2026");
    expect(within(row).getByText("Bank transfer")).toBeInTheDocument();
    expect(within(row).getByText("₹6,320.00")).toBeInTheDocument();
  });

  it("records a payment, filling the oldest first, and opens it", async () => {
    openItems();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/payments`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(payment(), { status: 201 });
      }),
      http.get(`${API}/payments/${PAY}`, () => HttpResponse.json(payment())),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/payments/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    await user.type(screen.getByLabelText("Amount received (₹)"), "3,30,000");
    await user.type(screen.getByLabelText("Reference"), "UTR123");
    await user.click(await screen.findByRole("button", { name: "Fill oldest first" }));
    expect(screen.getByLabelText("Allocate to INV/0001")).toHaveValue("323680.00");
    expect(screen.getByLabelText("Allocate to INV/0002")).toHaveValue("6320.00");
    expect(screen.getByLabelText("Allocate to RET/1")).toHaveValue("");
    const footer = screen.getByText("Left unallocated").closest("tr") as HTMLElement;
    expect(within(footer).getByText("₹0.00")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Record payment" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/payments/${PAY}`);
    });
    expect(body).toEqual({
      party_id: CLIENT,
      project_id: null,
      payment_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) as unknown,
      amount: "330000",
      mode: "BANK_TRANSFER",
      reference: "UTR123",
      notes: null,
      allocations: [
        { document_id: "d1", amount: "323680.00" },
        { document_id: "d2", amount: "6320.00" },
      ],
    });
  });

  it("will not send more than is owed or received", async () => {
    openItems();
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/payments/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    await user.type(screen.getByLabelText("Amount received (₹)"), "5000");
    await user.type(await screen.findByLabelText("Allocate to INV/0002"), "10600.01");
    expect(screen.getByText("INV/0002: more than the ₹10,600.00 outstanding.")).toBeInTheDocument();
    expect(screen.getByText("More than the ₹5,000.00 available.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record payment" })).toBeDisabled();
  });

  it("unwinds, allocates the rest to a retention release and voids", async () => {
    openItems();
    let current = payment();
    const calls: string[] = [];
    server.use(
      http.get(`${API}/payments/${PAY}`, () => HttpResponse.json(current)),
      http.delete(`${API}/allocations/al1`, () => {
        calls.push("unwind");
        current = payment({ allocations: [], allocated: "0.00", unallocated: "330000.00" });
        return new HttpResponse(null, { status: 204 });
      }),
      http.post(`${API}/payments/${PAY}/allocations`, async ({ request }) => {
        calls.push(`allocate ${JSON.stringify(await request.json())}`);
        current = payment({ unallocated: "310000.00", allocated: "20000.00", allocations: [] });
        return HttpResponse.json(current);
      }),
      http.post(`${API}/payments/${PAY}/void`, ({ request }) => {
        calls.push(`void ${request.headers.get("If-Match") ?? ""}`);
        current = payment({ status: "VOIDED", void_reason: "Bounced cheque", allocations: [] });
        return HttpResponse.json(current);
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/payments/${PAY}`);
    await user.click(await screen.findByRole("button", { name: "Unwind" }));
    await answerConfirm(user, "Unwind");
    expect(
      await screen.findByText("Not allocated: an advance from the client."),
    ).toBeInTheDocument();

    await user.type(await screen.findByLabelText("Allocate to RET/1"), "20000");
    await user.click(screen.getByRole("button", { name: "Allocate" }));
    await waitFor(() => {
      expect(calls).toContain(
        `allocate ${JSON.stringify({ allocations: [{ retention_release_id: "r1", amount: "20000.00" }] })}`,
      );
    });

    await user.click(screen.getByRole("button", { name: "Void payment…" }));
    const form = screen.getByRole("form", { name: "Void payment" });
    await user.type(within(form).getByLabelText("Reason"), "Bounced cheque");
    await user.click(within(form).getByRole("button", { name: "Void payment" }));
    expect(await screen.findByText("Voided")).toBeInTheDocument();
    expect(calls).toContain('void "v1"');
    expect(screen.queryByRole("button", { name: "Unwind" })).not.toBeInTheDocument();
  });
});

describe("settlement on documents", () => {
  const issuedDoc = (overrides: Record<string, unknown>) => ({
    id: "d1",
    version: 2,
    doc_type: "TAX_INVOICE",
    status: "ISSUED",
    doc_number: "INV/0001",
    doc_date: "2026-10-19",
    fy_start_year: 2026,
    due_date: null,
    valid_until: null,
    gst_registration_id: "r",
    party_id: CLIENT,
    party_name: "Skyline Developers",
    project_id: null,
    project_name: null,
    place_of_supply: "32",
    supply_type: "INTRA_STATE",
    is_gst_document: true,
    round_to_rupee: false,
    is_ra_bill: false,
    ra_sequence: null,
    totals: {
      subtotal: "100.00",
      cgst: "9.00",
      sgst: "9.00",
      igst: "0.00",
      cess: "0.00",
      round_off: "0.00",
      grand_total: "118.00",
      retention: "0.00",
      income_tax_tds: "0.00",
      gst_tds: "0.00",
      advance_recovery: "0.00",
      net_receivable: "118.00",
      amount_settled: "50.00",
      outstanding: "68.00",
    },
    issued_at: "2026-10-19T12:00:00Z",
    created_at: "",
    updated_at: "",
    notes: null,
    terms: null,
    lines: [],
    ...overrides,
  });

  it("an invoice shows what settled it", async () => {
    server.use(
      http.get(`${API}/documents/d1`, () => HttpResponse.json(issuedDoc({}))),
      http.get(`${API}/documents/d1/allocations`, () =>
        HttpResponse.json({
          document_id: "d1",
          doc_type: "TAX_INVOICE",
          applied: null,
          unapplied: null,
          allocations: [
            {
              id: "al1",
              document_id: "d1",
              doc_number: "INV/0001",
              retention_release_id: null,
              payment_id: PAY,
              credit_note_id: null,
              amount: "50.00",
              created_at: "2026-10-25T10:00:00Z",
            },
          ],
        }),
      ),
    );
    renderSignedIn("/documents/d1");
    const link = await screen.findByRole("link", { name: "Payment" });
    expect(link).toHaveAttribute("href", `/payments/${PAY}`);
    expect(screen.getByText("₹50.00", { selector: "td" })).toBeInTheDocument();
  });

  it("a credit note is applied to the client's open invoices", async () => {
    openItems();
    let body: unknown = null;
    server.use(
      http.get(`${API}/documents/cn1`, () =>
        HttpResponse.json(issuedDoc({ id: "cn1", doc_type: "CREDIT_NOTE", doc_number: "CN/0001" })),
      ),
      http.get(`${API}/documents/cn1/allocations`, () =>
        HttpResponse.json({
          document_id: "cn1",
          doc_type: "CREDIT_NOTE",
          applied: "0.00",
          unapplied: "8024.00",
          allocations: [],
        }),
      ),
      http.post(`${API}/documents/cn1/allocations`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          document_id: "cn1",
          doc_type: "CREDIT_NOTE",
          applied: "8024.00",
          unapplied: "0.00",
          allocations: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/cn1");
    expect(await screen.findByText("Apply to invoices")).toBeInTheDocument();
    expect(screen.queryByLabelText("Allocate to RET/1")).not.toBeInTheDocument(); // documents only
    await user.click(await screen.findByRole("button", { name: "Fill oldest first" }));
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => {
      expect(body).toEqual({ allocations: [{ document_id: "d1", amount: "8024.00" }] });
    });
  });
});
