import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

describe("removing a line (D.3)", () => {
  it("can be undone from the message", async () => {
    server.use(
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const first = await screen.findByRole("group", { name: "Line 1" });
    await user.type(within(first).getByLabelText("Description"), "Excavation");
    await user.click(screen.getByRole("button", { name: /Add line/ }));
    const second = await screen.findByRole("group", { name: "Line 2" });
    await user.type(within(second).getByLabelText("Description"), "Plastering");

    await user.click(screen.getByRole("button", { name: "Remove line 2" }));
    expect(screen.queryByRole("group", { name: "Line 2" })).toBeNull();
    expect(screen.getByText("Line 2 removed: Plastering.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    const back = await screen.findByRole("group", { name: "Line 2" });
    expect(within(back).getByLabelText("Description")).toHaveValue("Plastering");
  });
});
