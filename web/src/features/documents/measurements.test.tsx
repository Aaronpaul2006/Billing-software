import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Sent = { lines?: Record<string, unknown>[] };

describe("measurement sheet", () => {
  it("works out the line's quantity from the rows, deductions taken off", async () => {
    const previews: Sent[] = [];
    server.use(
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, async ({ request }) => {
        previews.push((await request.json()) as Sent);
        return problem(422, "validation_error");
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Description"), "Plastering");
    await user.type(within(line).getByLabelText("Rate (₹)"), "310");
    await user.click(within(line).getByRole("button", { name: /Add a measurement sheet/ }));

    const sheet = within(line).getByRole("group", { name: "Measurement sheet of line 1" });
    await user.type(within(sheet).getByLabelText("Row 1 description"), "Walls A and B");
    await user.type(within(sheet).getByLabelText("Row 1 nos"), "2");
    await user.type(within(sheet).getByLabelText("Row 1 length"), "10.5");
    await user.type(within(sheet).getByLabelText("Row 1 breadth"), "3.2");
    await user.click(within(sheet).getByRole("button", { name: "Add row" }));
    await user.type(within(sheet).getByLabelText("Row 2 description"), "Window");
    await user.type(within(sheet).getByLabelText("Row 2 length"), "2.5");
    await user.type(within(sheet).getByLabelText("Row 2 breadth"), "3");
    await user.click(within(sheet).getByLabelText("Row 2 is a deduction"));

    expect(within(sheet).getByText("Quantity: 59.7")).toBeInTheDocument();
    const quantity = within(line).getByLabelText("Quantity");
    await waitFor(() => {
      expect(quantity).toHaveValue("59.700");
    });
    expect(quantity).toHaveAttribute("readonly");
    await waitFor(() => {
      expect(previews.at(-1)?.lines?.[0]?.measurements).toEqual([
        { description: "Walls A and B", nos: "2", length: "10.5", breadth: "3.2", deduct: false },
        { description: "Window", nos: "1", length: "2.5", breadth: "3", deduct: true },
      ]);
    });

    await user.click(within(sheet).getByRole("button", { name: "Remove row 2 of line 1" }));
    await waitFor(() => {
      expect(quantity).toHaveValue("67.200");
    });
  });
});
