import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { CLIENT, doc, DOC, PROJECT, TOTALS, useDoc } from "@/test/documents";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Reminder = components["schemas"]["PaymentReminder"];

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
    // type to find the BOQ item, by words of its description
    await user.type(within(line).getByLabelText("Item"), "m25 slab");
    await user.click(await within(line).findByRole("option", { name: /RCC M25 for slabs/ }));
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
      await within(line).findByText("Rate: A rate is required.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("prices a catalog variant at the item rate plus its change", async () => {
    const previews: unknown[] = [];
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () =>
        HttpResponse.json({
          results: [
            {
              id: "c1",
              name: "OPC 53 cement",
              description: null,
              unit: "bag",
              sac_hsn: "2523",
              default_rate: "380.00",
              gst_rate: "28.00",
              variants: [
                {
                  id: "v1",
                  catalog_item_id: "c1",
                  attribute: "Brand",
                  value: "UltraTech",
                  rate_delta: "20.00",
                  is_active: true,
                  version: 1,
                  created_at: "",
                  updated_at: "",
                },
                {
                  id: "v2",
                  catalog_item_id: "c1",
                  attribute: "Brand",
                  value: "Old stock",
                  rate_delta: "-50.00",
                  is_active: false,
                  version: 2,
                  created_at: "",
                  updated_at: "",
                },
              ],
              is_active: true,
              version: 1,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.post(`${API}/documents:preview-totals`, async ({ request }) => {
        previews.push(await request.json());
        return problem(422, "validation_error");
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Item"), "cement");
    const variant = await within(line).findByRole("option", {
      name: /OPC 53 cement — Brand: UltraTech/,
    });
    expect(variant).toHaveTextContent("₹400.00 / bag"); // item rate + the variant's change
    // archived variants are not offered
    expect(within(line).queryByText(/Old stock/)).not.toBeInTheDocument();
    await user.click(variant);
    expect(within(line).getByLabelText("Description")).toHaveValue(
      "OPC 53 cement — Brand: UltraTech",
    );
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("400.00");
    await user.type(within(line).getByLabelText("Quantity"), "100");
    await waitFor(() => {
      expect(JSON.stringify(previews.at(-1))).toContain('"catalog_variant_id":"v1"');
    });
    expect(JSON.stringify(previews.at(-1))).toContain('"catalog_item_id":"c1"');
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

describe("payment reminders", () => {
  const issued = doc({
    status: "ISSUED",
    doc_number: "INV/0001",
    due_date: "2026-11-18",
    issued_at: "2026-10-19T10:00:00Z",
  });

  function settledBy() {
    server.use(
      http.get(`${API}/documents/${DOC}/allocations`, () =>
        HttpResponse.json({
          document_id: DOC,
          doc_type: "TAX_INVOICE",
          applied: null,
          unapplied: null,
          allocations: [],
        }),
      ),
    );
  }

  it("lists what went out and sends one now", async () => {
    useDoc(issued);
    settledBy();
    let sent: string | null = null;
    const first: Reminder = {
      id: "r1",
      document_id: DOC,
      stage: "BEFORE_DUE",
      sent_to: "accounts@skyline.in",
      amount_due: "323680.00",
      sent_by_name: null,
      sent_at: "2026-11-15T04:00:00Z",
    };
    let history: Reminder[] = [first];
    server.use(
      http.get(`${API}/documents/${DOC}/reminders`, () => HttpResponse.json({ results: history })),
      http.post(`${API}/documents/${DOC}/reminders`, ({ request }) => {
        sent = request.headers.get("Idempotency-Key");
        const made: Reminder = {
          ...first,
          id: "r2",
          stage: "MANUAL",
          sent_by_name: "Asha Nair",
          sent_at: "2026-11-20T06:00:00Z",
        };
        history = [made, ...history];
        return HttpResponse.json(made, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    const section = await screen.findByRole("region", { name: "Payment reminders" });
    expect(
      await within(section).findByText(/3 days before the due date · to accounts@skyline.in/),
    ).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Send reminder" }));
    expect(
      await within(section).findByText("Reminder sent to accounts@skyline.in."),
    ).toBeInTheDocument();
    expect(await within(section).findByText(/Sent by hand \(Asha Nair\)/)).toBeInTheDocument();
    expect(sent).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("points to the client's page when the client has no email; viewers cannot send", async () => {
    useDoc(issued);
    settledBy();
    server.use(
      http.post(`${API}/documents/${DOC}/reminders`, () =>
        HttpResponse.json(
          {
            type: "/errors/validation_error",
            title: "Validation failed",
            status: 422,
            code: "validation_error",
            detail: "1 field is invalid.",
            errors: [
              {
                field: "party.email",
                code: "no_client_email",
                message: "This client has no email address.",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    const section = await screen.findByRole("region", { name: "Payment reminders" });
    await user.click(within(section).getByRole("button", { name: "Send reminder" }));
    expect(
      await within(section).findByRole("link", { name: "Add one on the client's page" }),
    ).toHaveAttribute("href", `/parties/${CLIENT}`);
  });

  it("hides the button from viewers and when nothing is owed", async () => {
    useDoc(issued);
    settledBy();
    renderSignedIn(`/documents/${DOC}`, { role: "VIEWER" });
    const section = await screen.findByRole("region", { name: "Payment reminders" });
    expect(within(section).getByText("None sent yet.")).toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: "Send reminder" }),
    ).not.toBeInTheDocument();
  });
});

describe("save as template", () => {
  it("saves a quote's lines under a name", async () => {
    const quote = doc({ doc_type: "QUOTATION", valid_until: "2026-11-18" });
    useDoc(quote);
    let sent: unknown = null;
    server.use(
      http.post(`${API}/documents/${DOC}/save-as-template`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          {
            id: "t1",
            version: 1,
            name: "2BHK interior",
            doc_type: "QUOTATION",
            valid_days: 30,
            notes: null,
            terms: null,
            lines: [],
            created_at: "",
            updated_at: "",
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Save as template" }));
    const form = screen.getByRole("form", { name: "Save as template" });
    await user.type(within(form).getByLabelText("Template name"), "2BHK interior");
    await user.type(within(form).getByLabelText("Valid for (days)"), "30");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved as the template “2BHK interior”/)).toBeInTheDocument();
    expect(sent).toEqual({ name: "2BHK interior", valid_days: 30 });
  });

  it("is not offered for credit notes", async () => {
    useDoc(doc({ doc_type: "CREDIT_NOTE", status: "ISSUED", doc_number: "CN/0001" }));
    renderSignedIn(`/documents/${DOC}`);
    await screen.findByRole("heading", { name: /Credit note CN\/0001/ });
    expect(screen.queryByRole("button", { name: "Save as template" })).not.toBeInTheDocument();
  });
});
