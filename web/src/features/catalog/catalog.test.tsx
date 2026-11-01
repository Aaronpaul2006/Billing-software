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
