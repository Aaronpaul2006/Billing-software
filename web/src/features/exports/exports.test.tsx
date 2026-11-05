import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

import { browser } from "./exports";
import type { Export } from "./exports";

function exported(overrides: Partial<Export> = {}): Export {
  return {
    id: "x1",
    kind: "PAYMENTS",
    format: "CSV",
    params: { from: "2026-10-01", to: "2026-10-31" },
    status: "PENDING",
    file_name: null,
    size_bytes: null,
    row_count: null,
    warnings: [],
    error: null,
    created_at: "2026-10-22T10:00:00Z",
    finished_at: null,
    download_url: null,
    ...overrides,
  };
}

describe("exports", () => {
  it("makes a file, waits for it and downloads with a fresh link", async () => {
    let made = false;
    let sent: { body: unknown; key: string | null } | null = null;
    const ready = exported({
      status: "READY",
      file_name: "payments_2026-10-01_2026-10-31.csv",
      size_bytes: 2048,
      row_count: 12,
      download_url: "https://storage.example.test/old",
    });
    let polls = 0;
    server.use(
      http.get(`${API}/exports`, () => {
        if (!made) return HttpResponse.json({ results: [] });
        polls += 1;
        return HttpResponse.json({ results: [polls === 1 ? exported() : ready] });
      }),
      http.post(`${API}/exports`, async ({ request }) => {
        sent = { body: await request.json(), key: request.headers.get("Idempotency-Key") };
        made = true;
        return HttpResponse.json(exported(), { status: 202 });
      }),
      http.get(`${API}/exports/x1`, () =>
        HttpResponse.json({ ...ready, download_url: "https://storage.example.test/fresh" }),
      ),
    );
    const opened: string[] = [];
    vi.spyOn(browser, "open").mockImplementation((url) => {
      opened.push(url);
    });
    const user = userEvent.setup();
    renderSignedIn("/exports");
    expect(await screen.findByText("Nothing exported in the last 7 days.")).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "New export" });
    await user.selectOptions(within(form).getByLabelText("What"), "PAYMENTS");
    await user.selectOptions(within(form).getByLabelText("File"), "CSV");
    expect(within(form).queryByLabelText("Books")).not.toBeInTheDocument();
    await user.clear(within(form).getByLabelText("From"));
    await user.type(within(form).getByLabelText("From"), "2026-10-01");
    await user.clear(within(form).getByLabelText("To"));
    await user.type(within(form).getByLabelText("To"), "2026-10-31");
    await user.click(within(form).getByRole("button", { name: "Make the file" }));

    expect(await screen.findByText(/Making/)).toBeInTheDocument();
    const button = await screen.findByRole("button", {
      name: /Download payments_2026-10-01_2026-10-31.csv/,
    });
    expect(screen.getByText("12 rows · 2 KB")).toBeInTheDocument();
    await user.click(button);
    await waitFor(() => {
      expect(opened).toEqual(["https://storage.example.test/fresh"]);
    });
    expect(sent).toMatchObject({
      body: { kind: "PAYMENTS", format: "CSV", params: { from: "2026-10-01", to: "2026-10-31" } },
    });
    expect((sent as unknown as { key: string }).key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("shows why a file failed and the server's checks", async () => {
    server.use(
      http.get(`${API}/exports`, () =>
        HttpResponse.json({
          results: [
            exported({
              id: "x2",
              kind: "DOCUMENTS",
              status: "FAILED",
              error: "More than 100,000 rows: choose a shorter period.",
              finished_at: "2026-10-22T10:00:01Z",
            }),
          ],
        }),
      ),
      http.post(`${API}/exports`, () =>
        HttpResponse.json(
          {
            type: "/errors/validation_error",
            title: "Validation failed",
            status: 422,
            code: "validation_error",
            detail: "1 field is invalid.",
            errors: [{ field: "params.from", code: "invalid_dates", message: "After `to`." }],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/exports");
    expect(await screen.findByText(/choose a shorter period/)).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make the file" }));
    expect(await screen.findByText("After `to`.")).toBeInTheDocument();
  });

  it("makes the GSTR-1 file for a regular registration and shows its warnings", async () => {
    let sent: unknown = null;
    const registration = (id: string, type: string, gstin: string) => ({
      id,
      registration_type: type,
      gstin,
      state_code: "32",
      state_name: "Kerala",
      legal_name: "Nair Constructions",
      trade_name: null,
      address: { line1: "MG Road", city: "Kochi", state_code: "32", pincode: "682016" },
      is_default: true,
      is_active: true,
      version: 1,
      created_at: "",
      updated_at: "",
    });
    server.use(
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({
          results: [
            registration("r9", "COMPOSITION", "32AAACN9999A1Z5"),
            registration("r1", "REGULAR", "32AAACN1234A1Z5"),
          ],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/exports`, () =>
        HttpResponse.json({
          results: sent
            ? [
                exported({
                  kind: "GSTR1",
                  format: "JSON",
                  params: { gst_registration_id: "r1", period: "2026-09" },
                  status: "READY",
                  file_name: "gstr1_32AAACN1234A1Z5_092026.json",
                  size_bytes: 900,
                  row_count: 4,
                  warnings: [
                    "Import this file into the GST offline tool and check it before filing.",
                  ],
                }),
              ]
            : [],
        }),
      ),
      http.post(`${API}/exports`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(exported({ kind: "GSTR1", format: "JSON" }), { status: 202 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/exports?kind=GSTR1&period=2026-09");
    const form = await screen.findByRole("form", { name: "New export" });
    const select = await within(form).findByLabelText("GST registration");
    await waitFor(() => {
      expect(
        within(select)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["32AAACN1234A1Z5 · Kerala"]);
    });
    expect(within(form).getByLabelText("Month")).toHaveValue("2026-09");
    expect(within(form).queryByLabelText("File")).not.toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Make the file" }));
    expect(
      await screen.findByText(/Import this file into the GST offline tool/),
    ).toBeInTheDocument();
    expect(sent).toEqual({
      kind: "GSTR1",
      format: "JSON",
      params: { gst_registration_id: "r1", period: "2026-09" },
    });
  });

  it("makes the BOQ file for the project in the link, and project margins", async () => {
    const sent: unknown[] = [];
    server.use(
      http.get(`${API}/exports`, () => HttpResponse.json({ results: [] })),
      http.get(`${API}/projects`, () =>
        HttpResponse.json({
          results: [
            { id: "p1", code: "VILLA-1", name: "Villa at Kakkanad" },
            { id: "p2", code: "SCH-2", name: "School block" },
          ],
        }),
      ),
      http.post(`${API}/exports`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(exported({ kind: "BOQ", format: "XLSX" }), { status: 202 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/exports?kind=BOQ&project_id=p2");
    const form = await screen.findByRole("form", { name: "New export" });
    expect(within(form).getByLabelText("What")).toHaveValue("BOQ");
    const project = within(form).getByLabelText("Project");
    await waitFor(() => {
      expect(within(project).getAllByRole("option")).toHaveLength(2);
    });
    expect(project).toHaveValue("p2");
    expect(within(form).queryByLabelText("From")).not.toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Make the file" }));
    await waitFor(() => {
      expect(sent).toHaveLength(1);
    });

    await user.selectOptions(within(form).getByLabelText("What"), "PROJECTS");
    expect(within(form).queryByLabelText("Project")).not.toBeInTheDocument();
    expect(within(form).getByText(/Every project to date/)).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Make the file" }));
    await waitFor(() => {
      expect(sent).toHaveLength(2);
    });
    expect(sent).toEqual([
      { kind: "BOQ", format: "XLSX", params: { project_id: "p2" } },
      { kind: "PROJECTS", format: "XLSX", params: {} },
    ]);
  });
});
