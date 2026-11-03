import { screen, within } from "@testing-library/react";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function noReports() {
  server.use(
    http.get(`${API}/reports/dashboard`, () => new Promise<never>(() => undefined)),
    http.get(`${API}/reports/receivables`, () => new Promise<never>(() => undefined)),
  );
}

describe("first page after sign-in", () => {
  it("greets by first name and offers the quick actions", async () => {
    noReports();
    renderSignedIn("/", {}, { full_name: "Asha Nair" });
    expect(await screen.findByText(/, Asha$/)).toBeInTheDocument();
    const actions = screen.getByRole("navigation", { name: "Quick actions" });
    expect(within(actions).getByRole("link", { name: "New quotation" })).toHaveAttribute(
      "href",
      "/documents/new?type=QUOTATION",
    );
    expect(within(actions).getByRole("link", { name: "Record a payment" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set up your business" })).not.toBeInTheDocument();
  });

  it("shows owners what is left to set up", async () => {
    noReports();
    server.use(
      http.get(`${API}/tenant/setup`, () =>
        HttpResponse.json({
          gst_registration: true,
          number_series: false,
          client: true,
          project: false,
          first_bill: false,
          team: false,
          complete: false,
        }),
      ),
    );
    renderSignedIn("/");
    expect(await screen.findByRole("heading", { name: "Set up your business" })).toBeVisible();
    expect(
      screen.getByText("2 of 6 done. This list goes away once everything is set up."),
    ).toBeVisible();
    const steps = screen.getByRole("list", { name: "Setup steps" });
    expect(
      within(steps).getByRole("link", { name: "Set up your bill number series" }),
    ).toHaveAttribute("href", "/settings/series");
    expect(
      within(steps).queryByRole("link", { name: "Add your first client" }),
    ).not.toBeInTheDocument();
  });

  it("site engineers get only what they may do, and no checklist", async () => {
    noReports();
    renderSignedIn("/", { role: "SITE_ENGINEER" });
    const actions = await screen.findByRole("navigation", { name: "Quick actions" });
    expect(within(actions).getByRole("link", { name: "New bill" })).toBeInTheDocument();
    expect(
      within(actions).queryByRole("link", { name: "Record a payment" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set up your business" })).not.toBeInTheDocument();
  });
});
