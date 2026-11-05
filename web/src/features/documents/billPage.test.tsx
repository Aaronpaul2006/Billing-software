import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT, DOC, doc, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const steps = async () =>
  within(await screen.findByRole("list", { name: "Where this document is" }))
    .getAllByRole("listitem")
    .map((li) => li.textContent);

describe("bill page (D.8)", () => {
  it("a draft: Issue is the main action, the rest under More", async () => {
    useDoc(doc());
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    expect(await steps()).toEqual([
      "Draft (now)",
      "Issued (still to come)",
      "Paid (still to come)",
    ]);
    const actions = screen.getByRole("group", { name: "Actions" });
    const buttons = within(actions)
      .getAllByRole("button")
      .concat(within(actions).getAllByRole("link"))
      .map((b) => b.textContent.trim());
    expect(buttons).toEqual(["Issue…", "Preview PDF", "More", "Edit"]);
    await user.click(within(actions).getByRole("button", { name: "More" }));
    const menu = await screen.findByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((m) => m.textContent),
    ).toEqual(["Duplicate", "Delete draft"]);
  });

  it("an issued bill still owed: Record payment opens the form with its client", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001", issued_at: "2026-10-19T10:00:00Z" }));
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/retention-releases`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${DOC}`);
    expect(await steps()).toEqual([
      "Draft (done)",
      "Issued · 19 Oct 2026 (now)",
      "Paid (still to come)",
    ]);
    const record = screen.getByRole("link", { name: "Record payment" });
    expect(record).toHaveAttribute(
      "href",
      `/payments/new?party=${CLIENT}&name=Skyline%20Developers`,
    );
    await user.click(record);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/payments/new");
    });
    expect(await screen.findByDisplayValue("Skyline Developers")).toBeInTheDocument();
  });

  it("shows part paid, and nothing to change for a viewer", async () => {
    useDoc(
      doc({
        status: "ISSUED",
        doc_number: "INV/0001",
        totals: { ...doc().totals, amount_settled: "100000.00", outstanding: "223680.00" },
      }),
    );
    renderSignedIn(`/documents/${DOC}`, { role: "VIEWER" });
    expect(await steps()).toEqual([
      "Draft (done)",
      "Issued (done)",
      "Part paid (now)",
      "Paid (still to come)",
    ]);
    const actions = screen.getByRole("group", { name: "Actions" });
    expect(within(actions).queryByRole("link", { name: "Record payment" })).toBeNull();
    expect(within(actions).queryByRole("button", { name: "Alter…" })).toBeNull();
  });

  it("a line's measurements fold out under it", async () => {
    const base = doc().lines[0];
    if (!base) throw new Error("fixture");
    useDoc(
      doc({
        lines: [
          {
            ...base,
            measurements: [
              {
                row_no: 1,
                description: "Slab, grid A-B",
                nos: "1.000",
                length: "10.000",
                breadth: "5.000",
                height: "0.150",
                deduct: false,
                quantity: "7.500",
              },
              {
                row_no: 2,
                description: "Duct opening",
                nos: "1.000",
                length: "1.000",
                breadth: "1.000",
                height: "0.150",
                deduct: true,
                quantity: "0.150",
              },
            ],
          },
        ],
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByText("Measurements (2 rows)"));
    const table = screen.getByRole("table", { name: "Measurements for line 1" });
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.textContent);
    expect(rows).toEqual([
      "Slab, grid A-B1 × 10 × 5 × 0.157.5",
      "Duct opening (less)1 × 1 × 1 × 0.15−0.15",
    ]);
  });
});
