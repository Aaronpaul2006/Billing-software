import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Document = components["schemas"]["Document"];

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";
const PROJECT = "0192f5c4-0000-7000-8000-0000000000p1";
const DOC = "0192f5c4-0000-7000-8000-0000000000d1";

const TOTALS = {
  subtotal: "289000.00",
  cgst: "26010.00",
  sgst: "26010.00",
  igst: "0.00",
  cess: "0.00",
  round_off: "0.00",
  grand_total: "341020.00",
  retention: "14450.00",
  income_tax_tds: "2890.00",
  gst_tds: "0.00",
  advance_recovery: "0.00",
  net_receivable: "323680.00",
  amount_settled: "0.00",
  outstanding: "323680.00",
};

function doc(overrides: Partial<Document> = {}): Document {
  return {
    id: DOC,
    version: 1,
    doc_type: "TAX_INVOICE",
    status: "DRAFT",
    doc_number: null,
    doc_date: "2026-10-19",
    fy_start_year: 2026,
    due_date: null,
    valid_until: null,
    gst_registration_id: "r1",
    party_id: CLIENT,
    party_name: "Skyline Developers",
    project_id: PROJECT,
    project_name: "Villa at Kakkanad",
    place_of_supply: "32",
    supply_type: "INTRA_STATE",
    supply_category: "REGULAR",
    lut: false,
    reverse_charge: false,
    is_gst_document: true,
    round_to_rupee: false,
    is_ra_bill: false,
    ra_sequence: null,
    totals: TOTALS,
    issued_at: null,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    notes: null,
    terms: null,
    lines: [
      {
        line_no: 1,
        catalog_item_id: null,
        boq_item_id: "b1",
        description: "RCC M25 for slabs",
        sac_hsn: "995453",
        unit: "cum",
        quantity: "42.500",
        prev_cumulative_qty: null,
        up_to_date_qty: null,
        rate: "6800.00",
        discount_amount: "0.00",
        taxable_value: "289000.00",
        gst_rate: "18.00",
        cgst_amount: "26010.00",
        sgst_amount: "26010.00",
        igst_amount: "0.00",
        cess_amount: "0.00",
        line_total: "341020.00",
      },
    ],
    ...overrides,
  };
}

function useDoc(d: Document) {
  server.use(http.get(`${API}/documents/${d.id}`, () => HttpResponse.json(d)));
}

describe("documents list", () => {
  it("shows numbers, parties and what is owed; filters by type", async () => {
    const seen: string[] = [];
    server.use(
      http.get(`${API}/documents`, ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({
          results: [
            doc({ status: "ISSUED", doc_number: "INV/0001" }),
            doc({ id: "d2", doc_type: "QUOTATION", status: "DRAFT", project_name: null }),
          ],
          next_cursor: null,
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents");
    const issued = (await screen.findByRole("link", { name: "INV/0001" })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(issued).getByText("Skyline Developers")).toBeInTheDocument();
    expect(within(issued).getByText("₹3,23,680.00")).toBeInTheDocument(); // outstanding
    const draft = screen.getByRole("link", { name: "Draft" }).closest("tr") as HTMLElement;
    expect(within(draft).getByText("–")).toBeInTheDocument(); // a quotation owes nothing
    await user.selectOptions(screen.getByLabelText("Type"), "invoices");
    await waitFor(() => {
      expect(seen.at(-1)).toContain("doc_type=TAX_INVOICE,BILL_OF_SUPPLY"); // one value for django-filter
    });
  });
});

describe("document editor", () => {
  it("picks the client, project and BOQ item; shows the server's totals; saves a draft", async () => {
    const previews: unknown[] = [];
    const sent: { body?: Record<string, unknown> } = {};
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("client_party_id")).toBe(CLIENT);
        return HttpResponse.json({
          results: [{ id: PROJECT, code: "VILLA-1", name: "Villa at Kakkanad" }],
          next_cursor: null,
        });
      }),
      http.get(`${API}/projects/${PROJECT}/boq-items`, () =>
        HttpResponse.json({
          results: [
            {
              id: "b1",
              project_id: PROJECT,
              item_code: "2.1",
              description: "RCC M25 for slabs",
              unit: "cum",
              sac_hsn: "995453",
              contract_qty: "100.000",
              rate: "6800.00",
              gst_rate: "18.00",
              is_variation: false,
              sort_order: 1,
              version: 1,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, async ({ request }) => {
        previews.push(await request.json());
        return HttpResponse.json({
          place_of_supply: "32",
          supply_type: "INTRA_STATE",
          totals: TOTALS,
          lines: [
            {
              line_no: 1,
              taxable_value: "289000.00",
              cgst_amount: "26010.00",
              sgst_amount: "26010.00",
              igst_amount: "0.00",
              cess_amount: "0.00",
              line_total: "341020.00",
            },
          ],
        });
      }),
      http.post(`${API}/documents`, async ({ request }) => {
        sent.body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(doc(), { status: 201 });
      }),
    );
    useDoc(doc());
    const user = userEvent.setup();
    const router = renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    await user.selectOptions(await screen.findByLabelText("Project"), PROJECT);
    const line = screen.getByRole("group", { name: "Line 1" });
    await waitFor(() => {
      expect(within(line).getAllByRole("option").length).toBeGreaterThan(1);
    });
    await user.selectOptions(within(line).getByLabelText("Item"), "boq:b1");
    expect(within(line).getByLabelText("Description")).toHaveValue("RCC M25 for slabs");
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("6800.00");
    await user.type(within(line).getByLabelText("Quantity"), "42.5");

    const totals = await screen.findByLabelText("Totals", {}, { timeout: 3000 });
    expect(within(totals).getByText("₹3,41,020.00")).toBeInTheDocument();
    expect(within(totals).getByText("₹3,23,680.00")).toBeInTheDocument(); // receivable now
    expect(within(line).getByText("₹3,41,020.00")).toBeInTheDocument();
    expect(previews.length).toBeLessThanOrEqual(2); // debounced, not one per keystroke

    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/documents/${DOC}`);
    });
    expect(sent.body).toMatchObject({
      doc_type: "TAX_INVOICE",
      party_id: CLIENT,
      project_id: PROJECT,
      is_ra_bill: false,
      lines: [
        {
          boq_item_id: "b1",
          description: "RCC M25 for slabs",
          quantity: "42.5",
          rate: "6800.00",
          gst_rate: "18.00",
        },
      ],
    });
    expect((sent.body?.lines as Record<string, unknown>[])[0]).not.toHaveProperty(
      "discount_amount",
    );
  });

  it("shows the server's complaint under the line it is about", async () => {
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, () =>
        HttpResponse.json(
          {
            type: "/errors/validation_error",
            title: "Validation failed",
            status: 422,
            code: "validation_error",
            detail: "1 field is invalid.",
            errors: [{ field: "lines[0].rate", code: "required", message: "A rate is required." }],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Description"), "Cleaning");
    await user.type(within(line).getByLabelText("Quantity"), "1");
    expect(
      await within(line).findByText("rate: A rate is required.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("issued documents are not edited here", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    renderSignedIn(`/documents/${DOC}/edit`);
    expect(await screen.findByText(/Only drafts can be edited/)).toBeInTheDocument();
  });
});

describe("document page", () => {
  it("issues a draft with If-Match and an Idempotency-Key", async () => {
    let headers: Headers | null = null;
    useDoc(doc());
    server.use(
      http.post(`${API}/documents/${DOC}/issue`, ({ request }) => {
        headers = request.headers;
        return HttpResponse.json(
          doc({
            status: "ISSUED",
            doc_number: "INV/0001",
            version: 2,
            issued_at: "2026-10-19T12:00:00Z",
          }),
        );
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    expect(await screen.findByRole("heading", { name: "Tax invoice (draft)" })).toBeInTheDocument();
    expect(screen.getByText("RCC M25 for slabs")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Issue" }));
    expect(
      await screen.findByRole("heading", { name: "Tax invoice INV/0001" }),
    ).toBeInTheDocument();
    const sent = headers as unknown as Headers;
    expect(sent.get("If-Match")).toBe('"v1"');
    expect(sent.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByText("Outstanding")).toBeInTheDocument();
  });

  it("explains a missing number series and links to it", async () => {
    useDoc(doc());
    server.use(
      http.post(`${API}/documents/${DOC}/issue`, () =>
        problem(
          409,
          "series_missing",
          "No active TAX_INVOICE number series for this registration.",
        ),
      ),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Issue" }));
    const link = await screen.findByRole("link", { name: "Add a number series" });
    expect(link).toHaveAttribute("href", "/settings/series");
  });

  it("opens the stored PDF through a short link, or says it is being prepared", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    let ready = false;
    server.use(
      http.get(`${API}/documents/${DOC}/pdf`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("as")).toBe("link");
        return ready
          ? HttpResponse.json({ url: "https://s3.example/inv.pdf?sig=1", expires_in: 300 })
          : HttpResponse.json({ status: "rendering" }, { status: 202 });
      }),
    );
    const tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "PDF" }));
    expect(await screen.findByText(/being prepared/)).toBeInTheDocument();
    expect(tab.close).toHaveBeenCalled();
    ready = true;
    await user.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() => {
      expect(tab.location.href).toBe("https://s3.example/inv.pdf?sig=1");
    });
  });

  it("cancels with a reason", async () => {
    let body: unknown = null;
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    server.use(
      http.post(`${API}/documents/${DOC}/cancel`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(doc({ status: "CANCELLED", doc_number: "INV/0001", version: 2 }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Cancel document…" }));
    const form = screen.getByRole("form", { name: "Cancel document" });
    expect(within(form).getByRole("button", { name: "Cancel document" })).toBeDisabled();
    await user.type(within(form).getByLabelText("Reason"), "Wrong rate");
    await user.click(within(form).getByRole("button", { name: "Cancel document" }));
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(body).toEqual({ reason: "Wrong rate" });
  });

  it("converts an accepted quotation and opens the new draft", async () => {
    let body: unknown = null;
    useDoc(doc({ doc_type: "QUOTATION", status: "ACCEPTED", doc_number: "QT/0001" }));
    server.use(
      http.post(`${API}/documents/${DOC}/convert`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(doc({ id: "inv-draft" }), { status: 201 });
      }),
      http.get(`${API}/documents/inv-draft`, () => HttpResponse.json(doc({ id: "inv-draft" }))),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/projects/${PROJECT}/boq-items`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, () =>
        HttpResponse.json({
          place_of_supply: "32",
          supply_type: "INTRA_STATE",
          totals: TOTALS,
          lines: [],
        }),
      ),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Convert…" }));
    const form = screen.getByRole("form", { name: "Convert document" });
    await user.click(within(form).getByRole("button", { name: "Create draft" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/documents/inv-draft/edit");
    });
    expect(body).toMatchObject({ to: "TAX_INVOICE" });
  });
});

describe("number series", () => {
  it("adds a series and shows the next number", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/document-series`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({
          results: [
            {
              id: "r1",
              registration_type: "REGULAR",
              gstin: "32AAACN1234A1Z5",
              state_code: "32",
              state_name: "Kerala",
              legal_name: "Nair Constructions",
              trade_name: null,
              address: {},
              is_default: true,
              is_active: true,
              version: 1,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.post(`${API}/document-series`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/series");
    await user.click(await screen.findByRole("button", { name: "Add series" }));
    const form = screen.getByRole("form", { name: "New number series" });
    await user.selectOptions(await within(form).findByLabelText("Registration"), "r1");
    expect(within(form).getByText("INV/0001")).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Document type"), "QUOTATION");
    expect(within(form).getByText("QT/0001")).toBeInTheDocument();
    await user.clear(within(form).getByLabelText("Next number"));
    await user.type(within(form).getByLabelText("Next number"), "27");
    expect(within(form).getByText("QT/0027")).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Add series" }));
    await waitFor(() => {
      expect(body).toMatchObject({
        gst_registration_id: "r1",
        doc_type: "QUOTATION",
        prefix: "QT/",
        next_number: 27,
        pad_width: 4,
      });
    });
  });
});
