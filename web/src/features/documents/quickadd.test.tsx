import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type CatalogItem = components["schemas"]["CatalogItem"];

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";

function item(over: Partial<CatalogItem> = {}): CatalogItem {
  return {
    id: "c1",
    name: "River sand",
    description: null,
    unit: "cft",
    sac_hsn: "2505",
    default_rate: "60.00",
    gst_rate: "5.00",
    variants: [],
    is_active: true,
    last_used_at: "2026-11-01T10:00:00Z",
    version: 1,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function base(catalogQueries: URLSearchParams[] = []) {
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      catalogQueries.push(q);
      const results = q.get("q")
        ? [item({ id: "c2", name: "TMT steel bar", unit: "kg", default_rate: "72.00" })]
        : [item()];
      return HttpResponse.json({ results, next_cursor: null });
    }),
    http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
  );
}

describe("finding items on a bill", () => {
  it("shows recent items first, and picks with the keyboard", async () => {
    const queries: URLSearchParams[] = [];
    base(queries);
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    const box = within(line).getByRole("combobox", { name: "Item" });
    await user.click(box);
    expect(await within(line).findByRole("option", { name: /River sand/ })).toBeVisible();
    expect(within(line).getByText("Recently used")).toBeVisible();
    expect(queries.at(-1)?.get("used")).toBe("true");
    expect(queries.at(-1)?.get("ordering")).toBe("-last_used_at");

    await user.type(box, "steel");
    expect(await within(line).findByRole("option", { name: /TMT steel bar/ })).toBeVisible();
    expect(queries.at(-1)?.get("q")).toBe("steel");
    await user.keyboard("{Enter}");
    expect(within(line).getByLabelText("Description")).toHaveValue("TMT steel bar");
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("72.00");
    expect(within(line).getByLabelText("Unit")).toHaveValue("kg");
    expect(box).toHaveValue("TMT steel bar");
  });

  it("Esc closes the list without choosing", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.click(within(line).getByRole("combobox", { name: "Item" }));
    await within(line).findByRole("option", { name: /River sand/ });
    await user.keyboard("{Escape}");
    expect(within(line).queryByRole("listbox")).not.toBeInTheDocument();
    expect(within(line).getByLabelText("Description")).toHaveValue("");
  });
});

describe("adding an item or a client without leaving the bill", () => {
  it("adds a new item from what was typed and puts it on the line", async () => {
    base();
    let sent: unknown = null;
    server.use(
      http.post(`${API}/catalog-items`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          item({
            id: "c9",
            name: "Wall putty",
            unit: "kg",
            default_rate: "45.50",
            gst_rate: "18.00",
          }),
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.type(within(line).getByRole("combobox", { name: "Item" }), "Wall putty");
    await user.click(await within(line).findByRole("option", { name: /New item “Wall putty”/ }));

    const dialog = await screen.findByRole("dialog", { name: "New item" });
    expect(within(dialog).getByLabelText("Item name")).toHaveValue("Wall putty");
    await user.type(within(dialog).getByLabelText("Unit"), "kg");
    await user.type(within(dialog).getByLabelText("Rate (₹)"), "45.50");
    await user.click(within(dialog).getByRole("button", { name: "Save item" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(sent).toEqual({
      name: "Wall putty",
      unit: "kg",
      sac_hsn: null,
      default_rate: "45.50",
      gst_rate: "18.00",
    });
    expect(within(line).getByLabelText("Description")).toHaveValue("Wall putty");
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("45.50");
  });

  it("adds a new client, showing the server's error next to the field", async () => {
    base();
    let attempts = 0;
    server.use(
      http.post(`${API}/parties`, () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            {
              type: "/errors/validation_error",
              title: "Invalid",
              status: 422,
              code: "validation_error",
              detail: "Check the fields.",
              request_id: null,
              errors: [
                { field: "gstin", code: "invalid_gstin", message: "This GSTIN is not valid." },
              ],
            },
            { status: 422, headers: { "Content-Type": "application/problem+json" } },
          );
        }
        return HttpResponse.json({ id: "p9", display_name: "Kurian Homes" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.click(await screen.findByRole("button", { name: "New client" }));
    const dialog = await screen.findByRole("dialog", { name: "New client" });
    await user.type(within(dialog).getByLabelText("Client name"), "Kurian Homes");
    await user.selectOptions(within(dialog).getByLabelText("GST"), "REGISTERED");
    await user.type(within(dialog).getByLabelText("GSTIN"), "32abc");
    await user.click(within(dialog).getByRole("button", { name: "Save client" }));
    expect(await within(dialog).findByText("This GSTIN is not valid.")).toBeVisible();

    await user.click(within(dialog).getByRole("button", { name: "Save client" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText("Client")).toHaveValue("Kurian Homes");
  });

  it("site engineers find items but do not add items or clients", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new", { role: "SITE_ENGINEER" });
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.type(within(line).getByRole("combobox", { name: "Item" }), "Wall putty");
    await within(line).findByRole("option", { name: /TMT steel bar/ });
    expect(within(line).queryByRole("option", { name: /New item/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New client" })).not.toBeInTheDocument();
  });
});
