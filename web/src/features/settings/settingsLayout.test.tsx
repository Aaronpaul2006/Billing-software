import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

function useCompany() {
  server.use(
    http.get(`${API}/tenant`, () =>
      HttpResponse.json({
        id: "t1",
        legal_name: "Nair Constructions",
        trade_name: null,
        pan: null,
        status: "ACTIVE",
        plan: "standard",
        timezone: "Asia/Kolkata",
        version: 3,
        created_at: "",
        updated_at: "",
      }),
    ),
  );
}

describe("settings screen (D.11)", () => {
  it("opens on Company, with the sections as tabs beside it", async () => {
    useCompany();
    const router = renderSignedIn("/settings");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/settings/company");
    });
    const tabs = await screen.findByRole("navigation", { name: "Settings sections" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual([
      "Company",
      "Members",
      "GST registrations",
      "Number series",
      "Bill printing",
      "Tally export",
    ]);
    // marked once the redirect from /settings has rendered
    await waitFor(() => {
      expect(within(tabs).getByRole("link", { name: "Company" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    });
    expect(await screen.findByLabelText("Legal name")).toHaveValue("Nair Constructions");
    // the sidebar has one entry for all of them, marked as where you are
    const sidebar = screen.getByRole("navigation", { name: "Settings" });
    expect(within(sidebar).getByRole("link", { name: "Business settings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("Ctrl+K still jumps straight to a settings section", async () => {
    server.use(
      http.get(`${API}/reports/dashboard`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
      http.get(`${API}/tenant/setup`, () => problem(403, "permission_denied")),
    );
    const user = userEvent.setup();
    renderSignedIn("/");
    await screen.findByRole("navigation", { name: "Sell" });
    await user.keyboard("{Control>}k{/Control}");
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    await within(dialog).findByRole("combobox", { name: "Search, or jump to a page" });
    await user.keyboard("members");
    expect(within(dialog).getByRole("option", { name: /Members/ })).toBeInTheDocument();
  });
});
