import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function registration(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    registration_type: "REGULAR",
    gstin: "32AAACN1234A1Z5",
    state_code: "32",
    state_name: "Kerala",
    legal_name: "Nair Constructions",
    trade_name: null,
    address: { line1: "MG Road", city: "Kochi", state_code: "32", pincode: "682016" },
    is_default: true,
    is_active: true,
    version: 1,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    ...overrides,
  };
}

describe("GST registrations", () => {
  it("adds a registration: the state comes from the GSTIN", async () => {
    let rows: ReturnType<typeof registration>[] = [];
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({ results: rows, next_cursor: null }),
      ),
      http.post(`${API}/gst-registrations`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        rows = [registration()];
        return HttpResponse.json(rows[0], { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/gst-registrations");
    expect(await screen.findByText(/No registration yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add registration" }));
    const form = screen.getByRole("form", { name: "New GST registration" });
    await user.type(within(form).getByLabelText("GSTIN"), "32aaacn1234a1z5");
    await user.type(within(form).getByLabelText("Legal name"), "Nair Constructions");
    await user.type(within(form).getByLabelText("Address"), "MG Road");
    await user.type(within(form).getByLabelText("City"), "Kochi");
    await user.type(within(form).getByLabelText("PIN code"), "682016");
    expect(within(form).getByLabelText("Default for new documents")).toBeChecked(); // the first one
    await user.click(within(form).getByRole("button", { name: "Add registration" }));
    expect(await screen.findByText("32AAACN1234A1Z5")).toBeInTheDocument();
    expect(body).toEqual({
      registration_type: "REGULAR",
      gstin: "32AAACN1234A1Z5",
      legal_name: "Nair Constructions",
      trade_name: null,
      address: { line1: "MG Road", city: "Kochi", state_code: "32", pincode: "682016" },
      is_default: true,
    });
  });

  it("an unregistered business gives its state instead", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.post(`${API}/gst-registrations`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(registration({ gstin: null, registration_type: "UNREGISTERED" }), {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/gst-registrations");
    await user.click(await screen.findByRole("button", { name: "Add registration" }));
    const form = screen.getByRole("form", { name: "New GST registration" });
    await user.selectOptions(within(form).getByLabelText("Type"), "UNREGISTERED");
    expect(within(form).queryByLabelText("GSTIN")).not.toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("State"), "29");
    await user.type(within(form).getByLabelText("Legal name"), "Small Works");
    await user.type(within(form).getByLabelText("Address"), "1 Main Rd");
    await user.type(within(form).getByLabelText("City"), "Bengaluru");
    await user.type(within(form).getByLabelText("PIN code"), "560001");
    await user.click(within(form).getByRole("button", { name: "Add registration" }));
    await waitFor(() => {
      expect(body).not.toBeNull();
    });
    expect(body).toMatchObject({
      registration_type: "UNREGISTERED",
      gstin: null,
      state_code: "29",
      address: { state_code: "29" },
    });
  });

  it("the project form points to Settings when there is no registration", async () => {
    server.use(
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
    );
    renderSignedIn("/projects/new");
    const link = await screen.findByRole("link", { name: "Add one in Settings" });
    expect(link).toHaveAttribute("href", "/settings/gst-registrations");
  });
});
