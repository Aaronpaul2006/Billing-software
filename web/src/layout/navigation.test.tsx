import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { doc, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

function quietDashboard() {
  server.use(
    http.get(`${API}/reports/dashboard`, () => problem(403, "permission_denied")),
    http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
  );
}

describe("navigation (D.5)", () => {
  it("groups the sidebar by job", async () => {
    renderSignedIn("/");
    await screen.findByRole("navigation", { name: "Sell" });
    const groups = screen
      .getAllByRole("navigation")
      .map((n) => n.getAttribute("aria-label"))
      .filter((n) => n !== "Breadcrumb" && n !== "Quick actions"); // the sidebar's sections
    expect(groups).toEqual(["Sell", "Money", "Work", "Insight", "Settings"]);
    const sell = screen.getByRole("navigation", { name: "Sell" });
    expect(
      within(sell)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["Quotations", "Bills", "Templates"]);
  });

  it("shows a site engineer only what they can use", async () => {
    quietDashboard();
    renderSignedIn("/", { role: "SITE_ENGINEER" });
    const insight = await screen.findByRole("navigation", { name: "Insight" });
    expect(within(insight).queryByRole("link", { name: "Reports" })).toBeNull();
    expect(within(insight).queryByRole("link", { name: "Exports" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Settings" })).toBeNull();
    expect(screen.getByRole("link", { name: "Bills" })).toBeInTheDocument();
  });

  it("marks Quotations or Bills as the current page, and the title follows", async () => {
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents?type=quotations");
    expect(await screen.findByRole("heading", { name: "Quotations" })).toBeInTheDocument();
    const sell = screen.getByRole("navigation", { name: "Sell" });
    expect(within(sell).getByRole("link", { name: "Quotations" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(sell).getByRole("link", { name: "Bills" })).not.toHaveAttribute("aria-current");
    await user.click(within(sell).getByRole("link", { name: "Bills" }));
    expect(await screen.findByRole("heading", { name: "Bills" })).toBeInTheDocument();
    await waitFor(() => {
      expect(within(sell).getByRole("link", { name: "Bills" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    });
  });

  it("detail pages show where they are", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    renderSignedIn(`/documents/${doc().id}`);
    const trail = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Bills" })).toHaveAttribute(
      "href",
      "/documents?type=bills",
    );
    expect(within(trail).getByText(/INV\/0001/)).toHaveAttribute("aria-current", "page");
  });

  it('"?" shows the keyboard shortcuts, but not while typing', async () => {
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents");
    const search = await screen.findByRole("searchbox", { name: "Search documents" });
    await user.type(search, "?");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
    expect(search).toHaveValue("?");
    search.blur();
    await user.keyboard("?");
    const help = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(help).getByText("Save the draft and keep working")).toBeInTheDocument();
  });
});
