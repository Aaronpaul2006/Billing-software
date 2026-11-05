import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

describe("menu on phones (D.1)", () => {
  it("opens the sections, the account and sign out, and closes after choosing", async () => {
    server.use(
      http.get(`${API}/payments`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/");
    await user.click(await screen.findByRole("button", { name: "Open the menu" }));
    const panel = await screen.findByRole("dialog", { name: "Menu" });
    const main = within(panel).getByRole("navigation", { name: "Main" });
    expect(within(main).getByRole("link", { name: "Invoices & quotes" })).toBeInTheDocument();
    expect(within(panel).getByRole("navigation", { name: "Settings" })).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: /your account and sign out/ }),
    ).toBeInTheDocument();
    await user.click(within(main).getByRole("link", { name: "Payments" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/payments");
    });
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
  });

  it("closes with Esc and gives the focus back to the menu button", async () => {
    const user = userEvent.setup();
    renderSignedIn("/");
    const button = await screen.findByRole("button", { name: "Open the menu" });
    await user.click(button);
    await screen.findByRole("dialog", { name: "Menu" });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    });
    expect(button).toHaveFocus();
  });

  it("the company switcher's name starts with the company it shows", async () => {
    renderSignedIn("/");
    const switchers = await screen.findAllByRole("button", {
      name: /^Nair Constructions, company$/,
    });
    expect(switchers.length).toBeGreaterThan(0);
  });
});
