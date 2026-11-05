import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DOC, doc, TOTALS, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function useEditing() {
  useDoc(doc());
  server.use(
    http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/projects/:id/boq-items`, () =>
      HttpResponse.json({ results: [], next_cursor: null }),
    ),
    http.post(`${API}/documents:preview-totals`, () =>
      HttpResponse.json({
        place_of_supply: "32",
        supply_type: "INTRA_STATE",
        totals: TOTALS,
        lines: [
          {
            line_no: 1,
            taxable_value: "289000.00",
            cgst_amount: "26010.00",
            sgst_amount: "26010.00",
            igst_amount: "0.00",
            cess_amount: "0.00",
            line_total: "341020.00",
          },
        ],
      }),
    ),
  );
}

describe("bill editor layout (D.9)", () => {
  it("the save bar shows the running total next to Save", async () => {
    useEditing();
    renderSignedIn(`/documents/${DOC}/edit`);
    const total = await screen.findByText(/^Total ₹3,41,020\.00/);
    const bar = total.closest("[role=status]")?.parentElement as HTMLElement;
    expect(within(bar).getByRole("button", { name: "Save draft" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Save and keep working" })).toBeInTheDocument();
    expect(bar).toHaveClass("sticky");
    // each line field keeps its own name, though the titles are shown once on wide screens
    const line = screen.getByRole("group", { name: "Line 1" });
    expect(within(line).getByLabelText("Quantity")).toHaveValue("42.500");
    expect(within(line).getByText("₹3,41,020.00")).toBeInTheDocument();
  });

  it("a line's actions are in one menu; Esc closes it and stays on the bill", async () => {
    useEditing();
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${DOC}/edit`);
    await user.click(await screen.findByRole("button", { name: "Actions for line 1" }));
    const menu = await screen.findByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((m) => m.textContent),
    ).toEqual(["Move up", "Move down", "Insert a line below", "Remove line"]);
    // the only line can be neither moved nor removed
    expect(within(menu).getByRole("menuitem", { name: "Remove line" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
    expect(router.state.navigation.state).toBe("idle");
    expect(router.state.location.pathname).toBe(`/documents/${DOC}/edit`);
  });
});
