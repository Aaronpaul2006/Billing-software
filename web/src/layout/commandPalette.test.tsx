import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT, DOC, doc, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const NOTHING = { documents: [], parties: [], projects: [], catalog_items: [] };

function quiet() {
  server.use(
    http.get(`${API}/reports/dashboard`, () => problem(403, "permission_denied")),
    http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
    http.get(`${API}/tenant/setup`, () => problem(403, "permission_denied")),
    http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
  );
}

/** The search endpoint, recording what was asked. */
function useSearch(answer: (q: string) => object = () => NOTHING) {
  const asked: string[] = [];
  server.use(
    http.get(`${API}/search`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("q") ?? "";
      asked.push(q);
      return HttpResponse.json(answer(q));
    }),
  );
  return asked;
}

/** The open palette, once its contents (loaded on first use) are there. */
async function palette() {
  const dialog = await screen.findByRole("dialog", { name: "Search" });
  await within(dialog).findByRole("combobox", { name: "Search, or jump to a page" });
  return dialog;
}

const options = (box: HTMLElement) =>
  within(box)
    .getAllByRole("option")
    .map((o) => o.querySelector(".font-medium")?.textContent);

describe("command palette (D.6)", () => {
  it("Ctrl+K opens it with what the role can start and the pages", async () => {
    quiet();
    const user = userEvent.setup();
    renderSignedIn("/", { role: "SITE_ENGINEER" });
    await screen.findByRole("navigation", { name: "Sell" });
    await user.keyboard("{Control>}k{/Control}");
    const dialog = await palette();
    const input = within(dialog).getByRole("combobox", { name: "Search, or jump to a page" });
    // focused just after it appears (the palette's contents load on first use)
    await waitFor(() => {
      expect(input).toHaveFocus();
    });
    const create = within(dialog).getByRole("group", { name: "Create" });
    expect(options(create)).toEqual(["New bill", "New quotation", "Record an expense"]);
    const pages = options(within(dialog).getByRole("group", { name: "Go to" }));
    expect(pages).toContain("Bills");
    expect(pages).not.toContain("Reports"); // a site engineer's role has no reports
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      within(create).getAllByRole("option")[0]?.id,
    );
  });

  it("finds a bill on the server and opens it with Enter", async () => {
    const asked = useSearch((q) =>
      q === "sky"
        ? {
            ...NOTHING,
            documents: [
              {
                id: DOC,
                doc_type: "TAX_INVOICE",
                status: "ISSUED",
                doc_number: "INV/0002",
                doc_date: "2026-10-19",
                party_name: "Skyline Developers",
                grand_total: "118000.00",
              },
            ],
            parties: [
              {
                id: CLIENT,
                display_name: "Skyline Developers",
                gstin: null,
                is_customer: true,
                is_vendor: false,
                is_active: true,
              },
            ],
          }
        : NOTHING,
    );
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0002" }));
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/documents");
    // the sidebar's (the phone header has one too)
    const [search] = await screen.findAllByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("aria-keyshortcuts", "Control+K");
    await user.click(search as HTMLElement);
    const dialog = await palette();
    await user.keyboard("sky");
    const bills = await within(dialog).findByRole("group", { name: "Bills & quotations" });
    expect(within(bills).getByRole("option")).toHaveTextContent(
      "Tax invoice INV/0002Skyline Developers · 19 Oct 2026 · ₹1,18,000.00 · Issued",
    );
    expect(within(dialog).getByRole("status")).toHaveTextContent("2 results");
    expect(asked).toEqual(["sky"]); // once, after typing stopped
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/documents/${DOC}`);
    });
    expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument();
  });

  it("arrow keys choose a page; nothing found says so", async () => {
    quiet();
    useSearch();
    server.use(
      http.get(`${API}/payments`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/");
    await screen.findByRole("navigation", { name: "Sell" });
    await user.keyboard("{Control>}k{/Control}");
    const dialog = await palette();
    await user.keyboard("pay");
    const listbox = within(dialog).getByRole("listbox");
    expect(options(listbox)).toEqual(["Record a payment", "Payments"]);
    await user.keyboard("{ArrowDown}");
    const chosen = within(listbox).getByRole("option", { selected: true });
    expect(chosen).toHaveTextContent("Payments");
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/payments");
    });
    await user.keyboard("{Control>}k{/Control}");
    const again = await palette();
    await user.keyboard("zzqx");
    expect(await within(again).findByText("Nothing found for “zzqx”.")).toBeInTheDocument();
  });

  it("Esc closes it (and the shortcut help) without leaving the bill being edited", async () => {
    const draft = doc();
    useDoc(draft);
    server.use(
      http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${draft.id}/edit`);
    await screen.findByRole("group", { name: "Line 1" });
    await user.keyboard("{Control>}k{/Control}");
    await palette();
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument();
    });
    expect(router.state.location.pathname).toBe(`/documents/${draft.id}/edit`);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(); // no "Leave this bill?"
    expect(router.state.navigation.state).toBe("idle"); // and not on its way out
    // the same for the shortcut help ("?" with no box focused)
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("?");
    await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
    });
    expect(router.state.location.pathname).toBe(`/documents/${draft.id}/edit`);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(); // no "Leave this bill?"
    expect(router.state.navigation.state).toBe("idle"); // and not on its way out
  });
});
