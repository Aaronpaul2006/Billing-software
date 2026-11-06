import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT, DOC, doc, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

import { DISMISSED } from "./FirstBillGuide";

function firstBill(issued: boolean) {
  server.use(
    http.get(`${API}/tenant/setup`, () =>
      HttpResponse.json({
        gst_registration: true,
        number_series: true,
        client: true,
        project: false,
        first_bill: issued,
        team: false,
        complete: false,
      }),
    ),
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
  );
}

describe("guided first bill (Part B)", () => {
  beforeEach(() => {
    localStorage.removeItem(DISMISSED);
  });

  it("walks through the first bill, ticking each step", async () => {
    firstBill(false);
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const guide = await screen.findByRole("region", { name: "Your first bill" });
    const steps = within(guide).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[0]).toHaveAttribute("aria-current", "step");
    await user.type(screen.getByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    expect(within(steps[0] as HTMLElement).getByLabelText("Done")).toBeInTheDocument();
    expect(steps[1]).toHaveAttribute("aria-current", "step");
  });

  it("says the last step on the saved draft, and can be skipped for good", async () => {
    firstBill(false);
    useDoc(doc({ status: "DRAFT" }));
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    const guide = await screen.findByRole("region", { name: "Your first bill" });
    const last = within(guide).getAllByRole("listitem")[3] as HTMLElement;
    expect(last).toHaveAttribute("aria-current", "step");
    expect(last).toHaveTextContent("press Issue");
    await user.click(within(guide).getByRole("button", { name: "Skip the guide" }));
    expect(screen.queryByRole("region", { name: "Your first bill" })).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED)).toBe("true");
  });

  it("stays away once a bill is issued, unless asked for", async () => {
    firstBill(true);
    renderSignedIn("/documents/new");
    expect(await screen.findByLabelText("Client")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your first bill" })).not.toBeInTheDocument();
  });

  it("comes back with ?guide=1", async () => {
    firstBill(true);
    localStorage.setItem(DISMISSED, "true");
    renderSignedIn("/documents/new?guide=1");
    expect(await screen.findByRole("region", { name: "Your first bill" })).toBeInTheDocument();
  });
});
