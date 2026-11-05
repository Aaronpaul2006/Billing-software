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
    const sell = within(panel).getByRole("navigation", { name: "Sell" });
    expect(within(sell).getByRole("link", { name: "Bills" })).toBeInTheDocument();
    const money = within(panel).getByRole("navigation", { name: "Money" });
    expect(within(panel).getByRole("navigation", { name: "Settings" })).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: /your account and sign out/ }),
    ).toBeInTheDocument();
    await user.click(within(money).getByRole("link", { name: "Payments" }));
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

describe("theme and text size in the user menu (D.2)", () => {
  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
  });

  it("switches to dark and large text, and the menu shows the choice", async () => {
    const user = userEvent.setup();
    renderSignedIn("/");
    await user.click(await screen.findByRole("button", { name: /your account and sign out/ }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(screen.getByRole("menuitemcheckbox", { name: "Dark" })).toBeChecked();
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Large text" }));
    expect(document.documentElement.classList.contains("text-large")).toBe(true);
    expect(window.localStorage.getItem("app.theme")).toBe("dark");
  });
});
