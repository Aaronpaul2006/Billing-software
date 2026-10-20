import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Project = components["schemas"]["Project"];
type BoqItem = components["schemas"]["BoqItem"];

const PID = "0192f5c4-0000-7000-8000-0000000000p1";
const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";
const REG = "0192f5c4-0000-7000-8000-0000000000r1";

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: PID,
    code: "VILLA-1",
    name: "Villa at Kakkanad",
    client_party_id: CLIENT,
    client_name: "Skyline Developers",
    gst_registration_id: REG,
    site_address: { line1: "Plot 12", city: "Kochi", state_code: "32", pincode: "682030" },
    site_state_code: "32",
    contract_value: "4500000.00",
    retention_pct: "5.00",
    income_tax_tds_pct: "1.00",
    gst_tds_applicable: false,
    mobilisation_advance: "0.00",
    advance_recovery_pct: "0.00",
    status: "ACTIVE",
    start_date: null,
    end_date: null,
    version: 2,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    ...overrides,
  };
}

function item(overrides: Partial<BoqItem> = {}): BoqItem {
  return {
    id: "i1",
    project_id: PID,
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
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    ...overrides,
  };
}

const registrations = {
  results: [
    {
      id: REG,
      registration_type: "REGULAR",
      gstin: "32AAACN1234A1Z5",
      state_code: "32",
      state_name: "Kerala",
      legal_name: "Nair Constructions",
      trade_name: null,
      address: { line1: "x", city: "Kochi", state_code: "32", pincode: "682001" },
      is_default: true,
      is_active: true,
      version: 1,
      created_at: "2026-10-19T10:00:00Z",
      updated_at: "2026-10-19T10:00:00Z",
    },
  ],
  next_cursor: null,
};

describe("projects", () => {
  it("lists projects with their client", async () => {
    let status: string | null = null;
    server.use(
      http.get(`${API}/projects`, ({ request }) => {
        status = new URL(request.url).searchParams.get("status");
        return HttpResponse.json({ results: [project()], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/projects");
    const row = (await screen.findByRole("link", { name: "Villa at Kakkanad" })).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Skyline Developers")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Kerala")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("₹45,00,000.00")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "COMPLETED");
    await waitFor(() => {
      expect(status).toBe("COMPLETED");
    });
  });

  it("creates a project: picks the client, cleans amounts, puts the address in the site state", async () => {
    const user = userEvent.setup();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/gst-registrations`, () => HttpResponse.json(registrations)),
      http.get(`${API}/parties`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        expect(q.get("is_customer")).toBe("true");
        return HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        });
      }),
      http.post(`${API}/projects`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(project({ id: "new-p" }), { status: 201 });
      }),
      http.get(`${API}/projects/new-p`, () => HttpResponse.json(project({ id: "new-p" }))),
    );
    const router = renderSignedIn("/projects/new");
    await user.type(await screen.findByLabelText("Code"), "VILLA-1");
    await user.type(screen.getByLabelText("Name"), "Villa at Kakkanad");
    await user.type(screen.getByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    expect(screen.getByLabelText("Client")).toHaveValue("Skyline Developers");
    await user.selectOptions(await screen.findByLabelText("Bill from"), REG);
    await user.selectOptions(screen.getByLabelText("Site state"), "32");
    await user.type(screen.getByLabelText("Site address"), "Plot 12");
    await user.type(screen.getByLabelText("City"), "Kochi");
    await user.type(screen.getByLabelText("PIN code"), "682030");
    await user.type(screen.getByLabelText("Contract value (₹)"), "45,00,000");
    await user.clear(screen.getByLabelText("Retention (%)"));
    await user.type(screen.getByLabelText("Retention (%)"), "5");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/projects/new-p");
    });
    expect(body).toMatchObject({
      code: "VILLA-1",
      client_party_id: CLIENT,
      gst_registration_id: REG,
      site_state_code: "32",
      site_address: { line1: "Plot 12", city: "Kochi", state_code: "32", pincode: "682030" },
      contract_value: "4500000",
      retention_pct: "5",
      status: "ACTIVE",
      start_date: null,
    });
  });

  it("checks the form before sending", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${API}/gst-registrations`, () => HttpResponse.json(registrations)));
    renderSignedIn("/projects/new");
    await user.type(await screen.findByLabelText("Code"), "villa 1");
    await user.type(screen.getByLabelText("Retention (%)"), "0");
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByText("Letters, digits, - and _, up to 30.")).toBeInTheDocument();
    expect(screen.getByText("Choose the client.")).toBeInTheDocument();
    expect(screen.getByText("Choose the state of the site.")).toBeInTheDocument();
  });
});

describe("project page", () => {
  function common() {
    server.use(
      http.get(`${API}/projects/${PID}`, () => HttpResponse.json(project())),
      http.get(`${API}/gst-registrations`, () => HttpResponse.json(registrations)),
    );
  }

  it("shows details and moves between tabs", async () => {
    common();
    server.use(
      http.get(`${API}/projects/${PID}/boq-items`, () =>
        HttpResponse.json({ results: [item()], next_cursor: null }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn(`/projects/${PID}`);
    expect(await screen.findByRole("heading", { name: "Villa at Kakkanad" })).toBeInTheDocument();
    expect(screen.getByLabelText("Client")).toHaveValue("Skyline Developers");
    expect(screen.getByLabelText("Code")).toHaveValue("VILLA-1");
    await user.click(screen.getByRole("link", { name: "BOQ" }));
    expect(await screen.findByText("RCC M25 for slabs")).toBeInTheDocument();
    expect(screen.getByText("₹6,800.00")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("adds an item and explains why a billed item cannot be deleted", async () => {
    common();
    let items = [item()];
    let posted: unknown = null;
    server.use(
      http.get(`${API}/projects/${PID}/boq-items`, () =>
        HttpResponse.json({ results: items, next_cursor: null }),
      ),
      http.post(`${API}/projects/${PID}/boq-items`, async ({ request }) => {
        posted = await request.json();
        items = [...items, item({ id: "i2", item_code: "3.1", description: "Brickwork" })];
        return HttpResponse.json(items[1], { status: 201 });
      }),
      http.delete(`${API}/boq-items/i1`, () =>
        problem(409, "boq_item_billed", "This item has been billed and cannot be deleted."),
      ),
    );
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderSignedIn(`/projects/${PID}/boq`);
    await user.click(await screen.findByRole("button", { name: "Add item" }));
    const form = screen.getByRole("form", { name: "New BOQ item" });
    await user.type(within(form).getByLabelText("Item code"), "3.1");
    await user.type(within(form).getByLabelText("Description"), "Brickwork");
    await user.type(within(form).getByLabelText("Unit"), "sqm");
    await user.type(within(form).getByLabelText("Contract quantity"), "500");
    await user.type(within(form).getByLabelText("Rate (₹)"), "900");
    await user.click(within(form).getByRole("button", { name: "Add item" }));
    expect(await screen.findByText("Brickwork")).toBeInTheDocument();
    expect(posted).toMatchObject({
      item_code: "3.1",
      unit: "sqm",
      contract_qty: "500",
      rate: "900",
      gst_rate: "18",
      sac_hsn: null,
      is_variation: false,
    });

    await user.click(screen.getByRole("button", { name: "Delete 2.1" }));
    expect(
      await screen.findByText(/This item has been billed, so it cannot be deleted/),
    ).toBeInTheDocument();
  });

  it("imports a BOQ file: check first, then import", async () => {
    common();
    // Node's File, not jsdom's: in tests fetch and FormData come from Node, which
    // cannot read a jsdom File (request.formData() never resolves). Browsers are fine.
    const nodeBuffer = "node:buffer";
    const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
      File: typeof File;
    };
    const calls: { dryRun: string | null; file: string | null; key: string | null }[] = [];
    server.use(
      http.get(`${API}/projects/${PID}/boq-items`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.post(`${API}/projects/${PID}/boq-items:import`, async ({ request }) => {
        const form = await request.formData();
        const file = form.get("file");
        const dryRun = form.get("dry_run") as string | null;
        calls.push({
          dryRun,
          file: file === null ? null : "attached",
          key: request.headers.get("Idempotency-Key"),
        });
        if (calls.length === 1) {
          return HttpResponse.json(
            {
              type: "/errors/validation_error",
              title: "Validation failed",
              status: 422,
              code: "validation_error",
              detail: "2 fields are invalid.",
              errors: [
                { field: "rows[6].rate", code: "min_value", message: "Must be 0 or more." },
                {
                  field: "rows[9].item_code",
                  code: "duplicate_item_code",
                  message: "Also on row 5.",
                },
              ],
            },
            { status: 422 },
          );
        }
        const preview = {
          dry_run: dryRun === "true",
          count: 2,
          skipped_rows: [4, 8],
          ignored_columns: ["Amount"],
          items: [item(), item({ id: "i2", item_code: "3.1", description: "Brickwork" })],
        };
        return HttpResponse.json(preview, { status: dryRun === "true" ? 200 : 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/projects/${PID}/boq`);
    await user.click(await screen.findByRole("button", { name: "Import from file" }));
    const input = screen.getByLabelText("BOQ file (CSV or Excel)");
    await user.upload(input, new NodeFile(["item_code,..."], "boq.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText("Fix these rows and upload again")).toBeInTheDocument();
    expect(screen.getByText("Row 6 · rate")).toBeInTheDocument();
    expect(screen.getByText("Row 9 · item_code")).toBeInTheDocument();

    await user.upload(input, new NodeFile(["fixed"], "boq-fixed.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText(/ready to import/)).toBeInTheDocument();
    expect(screen.getByText(/Skipped heading \/ total rows: 4, 8/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import 2 items" }));
    expect(await screen.findByText("Imported 2 items.")).toBeInTheDocument();

    // (Which file was sent cannot be seen here: the test FormData is jsdom's.)
    expect(calls.map((c) => [c.dryRun, c.file])).toEqual([
      ["true", "attached"],
      ["true", "attached"],
      ["false", "attached"],
    ]);
    expect(calls[1]?.key).not.toBe(calls[0]?.key); // another file: another action
    expect(calls[2]?.key).not.toBe(calls[1]?.key); // checking and importing are different actions
  });

  it("shows progress against the BOQ", async () => {
    common();
    server.use(
      http.get(`${API}/projects/${PID}/boq-progress`, () =>
        HttpResponse.json({
          results: [
            {
              boq_item_id: "i1",
              item_code: "2.1",
              description: "RCC M25",
              unit: "cum",
              rate: "6800.00",
              is_variation: false,
              contract_qty: "100.000",
              billed_qty: "42.500",
              balance_qty: "57.500",
              contract_value: "680000.00",
              billed_value: "289000.00",
              progress_pct: "42.50",
            },
          ],
          totals: { contract_value: "680000.00", billed_value: "289000.00", progress_pct: "42.50" },
        }),
      ),
    );
    renderSignedIn(`/projects/${PID}/progress`);
    expect(await screen.findByText("57.5")).toBeInTheDocument();
    expect(screen.getAllByText("42.5 %")).toHaveLength(2);
  });

  it("retention: what is held, recording a release and cancelling one", async () => {
    common();
    let releases = [
      {
        id: "rel1",
        version: 1,
        project_id: PID,
        party_id: CLIENT,
        book: "GST",
        release_date: "2026-11-05",
        due_date: null,
        amount: "5000.00",
        amount_settled: "0.00",
        outstanding: "5000.00",
        reference: "SKY/RET/1",
        notes: null,
        status: "RELEASED",
        cancelled_at: null,
        cancel_reason: null,
        created_at: "",
        updated_at: "",
      },
    ];
    const calls: string[] = [];
    server.use(
      http.get(`${API}/projects/${PID}/retention`, () =>
        HttpResponse.json({
          project_id: PID,
          GST: { deducted: "28900.00", released: "5000.00", available: "23900.00" },
          NON_GST: { deducted: "0.00", released: "0.00", available: "0.00" },
        }),
      ),
      http.get(`${API}/retention-releases`, () =>
        HttpResponse.json({ results: releases, next_cursor: null }),
      ),
      http.post(`${API}/retention-releases`, async ({ request }) => {
        calls.push(`create ${JSON.stringify(await request.json())}`);
        return HttpResponse.json({}, { status: 201 });
      }),
      http.post(`${API}/retention-releases/rel1/cancel`, async ({ request }) => {
        calls.push(
          `cancel ${request.headers.get("If-Match") ?? ""} ${JSON.stringify(await request.json())}`,
        );
        releases = releases.map((r) => ({ ...r, status: "CANCELLED", outstanding: "0.00" }));
        return HttpResponse.json(releases[0]);
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/projects/${PID}/retention`);
    expect(await screen.findByText("₹23,900.00")).toBeInTheDocument(); // still held
    expect(screen.getByText("SKY/RET/1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Record release" }));
    const form = screen.getByRole("form", { name: "New retention release" });
    await user.type(within(form).getByLabelText("Amount released (₹)"), "10,000");
    await user.type(within(form).getByLabelText("Reference"), "SKY/RET/2");
    await user.click(within(form).getByRole("button", { name: "Record release" }));
    await waitFor(() => {
      expect(calls[0]).toContain('"amount":"10000"');
    });
    expect(calls[0]).toContain('"book":"GST"');
    expect(calls[0]).toContain('"reference":"SKY/RET/2"');

    await user.click(screen.getByRole("button", { name: "Cancel…" }));
    await user.type(screen.getByLabelText("Reason"), "Client withdrew");
    await user.click(screen.getByRole("button", { name: "Cancel release" }));
    await waitFor(() => {
      expect(calls[1]).toBe('cancel "v1" {"reason":"Client withdrew"}');
    });
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
  });
});
