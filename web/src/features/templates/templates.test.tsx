import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

import type { Template } from "./templates";

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";

function template(over: Partial<Template> = {}): Template {
  return {
    id: "t1",
    version: 2,
    name: "2BHK interior",
    doc_type: "QUOTATION",
    valid_days: 30,
    notes: null,
    terms: null,
    lines: [
      {
        description: "Interior emulsion, 2 coats",
        sac_hsn: "995473",
        unit: "sqm",
        quantity: "420.000",
        rate: "65.50",
        discount_amount: "0.00",
        gst_rate: "18.00",
      },
    ],
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function listed(items: Template[]) {
  server.use(
    http.get(`${API}/document-templates`, () =>
      HttpResponse.json({ results: items, next_cursor: null }),
    ),
  );
}

describe("templates", () => {
  it("starts a draft for a client and project, then opens it in the editor", async () => {
    listed([template()]);
    let used: { body: unknown; key: string | null } | null = null;
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
          results: [{ id: "p1", code: "VILLA-1", name: "Villa" }],
          next_cursor: null,
        });
      }),
      http.post(`${API}/document-templates/t1/use`, async ({ request }) => {
        used = { body: await request.json(), key: request.headers.get("Idempotency-Key") };
        return HttpResponse.json({ id: "d9" }, { status: 201 });
      }),
      http.get(`${API}/documents/d9`, () => problem(404, "not_found")),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/templates");
    expect(await screen.findByText("Quotation · 1 line · valid 30 days")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use" }));
    const form = screen.getByRole("form", { name: "Use 2BHK interior" });
    await user.type(within(form).getByLabelText("Client"), "sky");
    await user.click(await within(form).findByRole("button", { name: /Skyline Developers/ }));
    await waitFor(() => {
      expect(within(form).getAllByRole("option")).toHaveLength(2);
    });
    await user.selectOptions(within(form).getByLabelText("Project"), "p1");
    await user.clear(within(form).getByLabelText("Date"));
    await user.type(within(form).getByLabelText("Date"), "2026-11-01");
    await user.click(within(form).getByRole("button", { name: "Create the draft" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/documents/d9/edit");
    });
    expect(used).toEqual({
      body: { party_id: CLIENT, project_id: "p1", doc_date: "2026-11-01" },
      key: expect.stringMatching(/^[0-9a-f-]{36}$/) as unknown,
    });
  });

  it("renames with If-Match and deletes after asking", async () => {
    let items = [template()];
    const calls: string[] = [];
    server.use(
      http.get(`${API}/document-templates`, () =>
        HttpResponse.json({ results: items, next_cursor: null }),
      ),
      http.patch(`${API}/document-templates/t1`, async ({ request }) => {
        calls.push(
          `rename ${request.headers.get("If-Match") ?? ""} ${JSON.stringify(await request.json())}`,
        );
        items = [template({ name: "2BHK interior (2026)", version: 3 })];
        return HttpResponse.json(items[0]);
      }),
      http.delete(`${API}/document-templates/t1`, () => {
        calls.push("delete");
        items = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderSignedIn("/templates");
    await user.click(await screen.findByRole("button", { name: "Rename" }));
    const name = screen.getByLabelText("New name");
    await user.clear(name);
    await user.type(name, "2BHK interior (2026)");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("2BHK interior (2026)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete 2BHK interior (2026)" }));
    expect(await screen.findByText(/No templates yet/)).toBeInTheDocument();
    expect(calls).toEqual(['rename "v2" {"name":"2BHK interior (2026)"}', "delete"]);
  });

  it("lets viewers look but not use or change", async () => {
    listed([template()]);
    renderSignedIn("/templates", { role: "VIEWER" });
    expect(await screen.findByText("2BHK interior")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });
});
