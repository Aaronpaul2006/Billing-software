import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Item = components["schemas"]["CatalogItem"];
type Variant = components["schemas"]["CatalogVariant"];

function variant(over: Partial<Variant> = {}): Variant {
  return {
    id: "v1",
    catalog_item_id: "c1",
    attribute: "Brand",
    value: "UltraTech",
    rate_delta: "20.00",
    is_active: true,
    version: 1,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function item(variants: Variant[]): Item {
  return {
    id: "c1",
    name: "OPC 53 cement",
    description: null,
    unit: "bag",
    sac_hsn: "2523",
    default_rate: "380.00",
    gst_rate: "28.00",
    variants,
    last_used_at: null,
    is_active: true,
    version: 1,
    created_at: "",
    updated_at: "",
  };
}

describe("catalog", () => {
  it("shows an item's variants with their rates, adds one, explains a used one", async () => {
    let variants = [variant()];
    let added: unknown = null;
    server.use(
      http.get(`${API}/catalog-items`, () =>
        HttpResponse.json({ results: [item(variants)], next_cursor: null }),
      ),
      http.post(`${API}/catalog-items/c1/variants`, async ({ request }) => {
        added = await request.json();
        const v = variant({ id: "v2", value: "Local", rate_delta: "-15.00" });
        variants = [...variants, v];
        return HttpResponse.json(v, { status: 201 });
      }),
      http.delete(`${API}/catalog-variants/v1`, () =>
        problem(409, "variant_used", "Documents use this variant."),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/catalog");
    expect(
      await screen.findByText("₹380.00 per bag · GST 28.00 % · HSN/SAC 2523 · 1 variant"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Variants" }));
    const section = screen.getByRole("region", { name: "Variants of OPC 53 cement" });
    expect(within(section).getByText("+₹20.00 → ₹400.00")).toBeInTheDocument();

    const form = within(section).getByRole("form", { name: "Add a variant of OPC 53 cement" });
    await user.type(within(form).getByLabelText("What varies"), "Brand");
    await user.type(within(form).getByLabelText("Value"), "Local");
    await user.type(within(form).getByLabelText("Rate change (₹)"), "-15");
    await user.click(within(form).getByRole("button", { name: "Add variant" }));
    expect(await within(section).findByText("-₹15.00 → ₹365.00")).toBeInTheDocument();
    expect(added).toEqual({ attribute: "Brand", value: "Local", rate_delta: "-15" });

    await user.click(within(section).getByRole("button", { name: "Delete Brand: UltraTech" }));
    expect(
      await within(section).findByText(/Bills use this variant: archive it instead/),
    ).toBeInTheDocument();
  });

  it("is read-only for site engineers", async () => {
    server.use(
      http.get(`${API}/catalog-items`, () =>
        HttpResponse.json({ results: [item([variant()])], next_cursor: null }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/catalog", { role: "SITE_ENGINEER" });
    await user.click(await screen.findByRole("button", { name: "Variants" }));
    await waitFor(() => {
      expect(screen.getByText("+₹20.00 → ₹400.00")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Add item" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: /Add a variant/ })).not.toBeInTheDocument();
  });
});

describe("catalog search and import", () => {
  it("searches by what is typed", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${API}/catalog-items`, ({ request }) => {
        const q = new URL(request.url).searchParams.get("q");
        seen.push(q);
        return HttpResponse.json({ results: q ? [] : [item([])], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/catalog");
    await screen.findByText(/₹380.00 per bag/);
    await user.type(screen.getByRole("searchbox", { name: "Search items" }), "ultratech");
    expect(await screen.findByText("No item matches.")).toBeInTheDocument();
    expect(seen.at(-1)).toBe("ultratech");
  });

  it("checks a file, shows row errors in plain words, then imports", async () => {
    // Node's File, not jsdom's: Node's fetch cannot read a jsdom File (see projects.test.tsx)
    const nodeBuffer = "node:buffer";
    const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
      File: typeof File;
    };
    const calls: string[] = [];
    let attempt = 0;
    server.use(
      http.get(`${API}/catalog-items`, () =>
        HttpResponse.json({ results: [item([])], next_cursor: null }),
      ),
      http.post(`${API}/catalog-items:import`, async ({ request }) => {
        const dryRun = (await request.formData()).get("dry_run") as string;
        calls.push(dryRun);
        attempt += 1;
        if (attempt === 1) {
          return HttpResponse.json(
            {
              type: "/errors/validation_error",
              title: "Invalid",
              status: 422,
              code: "validation_error",
              detail: "Check the rows.",
              request_id: null,
              errors: [
                { field: "rows[3].sac_hsn", code: "invalid", message: "Use 4 to 8 digits." },
              ],
            },
            { status: 422, headers: { "Content-Type": "application/problem+json" } },
          );
        }
        const body = {
          dry_run: dryRun === "true",
          count: 2,
          skipped_rows: [],
          ignored_columns: [],
          items: [
            { ...item([]), id: null, name: "Wall putty", default_rate: "1250.50" },
            { ...item([]), id: null, name: "M-sand" },
          ],
        };
        return HttpResponse.json(body, { status: dryRun === "true" ? 200 : 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/catalog");
    await user.click(await screen.findByRole("button", { name: "Import from Excel" }));
    const region = screen.getByRole("region", { name: "Import items" });
    const input = within(region).getByLabelText("Items file (CSV or Excel)");
    await user.upload(input, new NodeFile(["Item name\n"], "items.csv", { type: "text/csv" }));
    await user.click(within(region).getByRole("button", { name: "Check file" }));
    expect(await within(region).findByText("Row 3 · HSN/SAC")).toBeInTheDocument();

    await user.upload(input, new NodeFile(["fixed"], "items-fixed.csv", { type: "text/csv" }));
    await user.click(within(region).getByRole("button", { name: "Check file" }));
    expect(await within(region).findByText("Wall putty")).toBeInTheDocument();
    expect(within(region).getByText("₹1,250.50")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Import 2 items" }));
    expect(await within(region).findByText("Imported 2 items.")).toBeInTheDocument();
    expect(calls).toEqual(["true", "true", "false"]);
  });

  it("downloads the sample file", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${API}/catalog-items`, () =>
        HttpResponse.json({ results: [item([])], next_cursor: null }),
      ),
      http.get(`${API}/catalog-items:import-sample`, ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("type") ?? "");
        return new HttpResponse("Item name\n", { headers: { "Content-Type": "text/csv" } });
      }),
    );
    const created = vi.fn(() => "blob:sample");
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderSignedIn("/catalog");
    await user.click(await screen.findByRole("button", { name: "Import from Excel" }));
    await user.click(screen.getByRole("button", { name: "CSV" }));
    await waitFor(() => {
      expect(click).toHaveBeenCalled();
    });
    expect(asked).toEqual(["csv"]);
    expect(created).toHaveBeenCalled();
  });
});
