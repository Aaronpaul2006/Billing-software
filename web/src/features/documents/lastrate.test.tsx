import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

describe("last rate for this client", () => {
  it("shows the rate on the client's last bill, and uses it in one click", async () => {
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
              variants: [],
              is_active: true,
              last_used_at: null,
              version: 1,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/parties/${CLIENT}/last-rates`, () =>
        HttpResponse.json({
          results: [
            {
              catalog_item_id: "c1",
              catalog_variant_id: null,
              rate: "395.00",
              document_id: "d9",
              doc_number: "INV/0012",
              doc_date: "2026-10-12",
            },
          ],
        }),
      ),
      http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByRole("combobox", { name: "Item" }), "cement");
    await user.click(await within(line).findByRole("option", { name: /OPC 53 cement/ }));
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("380.00");
    expect(
      await within(line).findByText(/Last charged to this client: ₹395.00 on INV\/0012/),
    ).toBeInTheDocument();

    await user.click(within(line).getByRole("button", { name: "Use ₹395.00" }));
    expect(within(line).getByLabelText("Rate (₹)")).toHaveValue("395.00");
    expect(within(line).queryByText(/Last charged/)).not.toBeInTheDocument(); // same rate now
  });
});
