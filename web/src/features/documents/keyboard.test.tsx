import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT, doc, DOC, PROJECT, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

function base({ projects = 1 }: { projects?: number } = {}) {
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () =>
      HttpResponse.json({
        results: Array.from({ length: projects }, (_, i) => ({
          id: i === 0 ? PROJECT : `p${String(i)}`,
          code: `P${String(i + 1)}`,
          name: `Site ${String(i + 1)}`,
        })),
        next_cursor: null,
      }),
    ),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/projects/:id/boq-items`, () =>
      HttpResponse.json({ results: [], next_cursor: null }),
    ),
    http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
  );
}

async function chooseClient(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Client"), "sky");
  await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
}

describe("keyboard-first bill screen", () => {
  it("Enter moves to the next box, and past the last line adds a new one", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.click(within(line).getByLabelText("Description"));
    await user.keyboard("RCC work{Enter}");
    expect(within(line).getByLabelText("Quantity")).toHaveFocus();
    await user.keyboard("10{Enter}");
    expect(within(line).getByLabelText("Unit")).toHaveFocus();
    await user.click(within(line).getByLabelText("HSN/SAC")); // the line's last box
    await user.keyboard("{Enter}");
    const second = await screen.findByRole("group", { name: "Line 2" });
    await waitFor(() => {
      expect(within(second).getByRole("combobox", { name: "Item" })).toHaveFocus();
    });
  });

  it("Alt+N adds a line; Alt+/ shows the shortcuts; Esc hides them", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await screen.findByRole("group", { name: "Line 1" });
    await user.keyboard("{Alt>}n{/Alt}");
    expect(await screen.findByRole("group", { name: "Line 2" })).toBeInTheDocument();
    await user.keyboard("{Alt>}/{/Alt}");
    const help = await screen.findByRole("region", { name: "Keyboard shortcuts" });
    expect(within(help).getByText("Save the draft and keep working")).toBeVisible();
    await user.keyboard("{Escape}"); // first closes the new line's item list
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
  });

  it("Ctrl+S saves and keeps the bill open; Ctrl+Enter opens it", async () => {
    base();
    const saved = doc();
    useDoc(saved);
    const posts: unknown[] = [];
    server.use(
      http.post(`${API}/documents`, async ({ request }) => {
        posts.push(await request.json());
        return HttpResponse.json(saved, { status: 201 });
      }),
      http.patch(`${API}/documents/${DOC}`, () => HttpResponse.json({ ...saved, version: 2 })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/documents/new");
    await chooseClient(user);
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Description"), "RCC work");
    await user.type(within(line).getByLabelText("Quantity"), "10");
    await user.keyboard("{Control>}s{/Control}");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/documents/${DOC}/edit`);
    });
    expect(posts).toHaveLength(1);
    expect(await screen.findByRole("status")).toHaveTextContent(/Saved at/);

    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/documents/${DOC}`);
    });
  });

  it("moves and inserts lines", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const first = await screen.findByRole("group", { name: "Line 1" });
    await user.type(within(first).getByLabelText("Description"), "Excavation");
    await user.click(screen.getByRole("button", { name: "Insert a line below line 1" }));
    const second = await screen.findByRole("group", { name: "Line 2" });
    await user.type(within(second).getByLabelText("Description"), "Backfilling");
    await user.click(screen.getByRole("button", { name: "Move line 2 up" }));
    expect(
      within(screen.getByRole("group", { name: "Line 1" })).getByLabelText("Description"),
    ).toHaveValue("Backfilling");
    expect(
      within(screen.getByRole("group", { name: "Line 2" })).getByLabelText("Description"),
    ).toHaveValue("Excavation");
  });

  it("picks the client's only project and shows what they owe", async () => {
    base();
    server.use(
      http.get(`${API}/parties/${CLIENT}/statement`, () =>
        HttpResponse.json({ closing_balance: "323680.00" }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await chooseClient(user);
    await waitFor(() => {
      expect(screen.getByLabelText("Project")).toHaveValue(PROJECT);
    });
    expect(await screen.findByText("Owes you now: ₹3,23,680.00")).toBeInTheDocument();
  });

  it("with several projects, picks the one on the client's last bill", async () => {
    base({ projects: 3 });
    server.use(
      http.get(`${API}/documents`, ({ request }) =>
        HttpResponse.json({
          results:
            new URL(request.url).searchParams.get("party_id") === CLIENT
              ? [{ ...doc(), project_id: "p2" }]
              : [],
          next_cursor: null,
        }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await chooseClient(user);
    await waitFor(() => {
      expect(screen.getByLabelText("Project")).toHaveValue("p2");
    });
  });

  it("asks before leaving with unsaved changes", async () => {
    base();
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    const router = renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Description"), "RCC");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(ask).toHaveBeenCalled();
    expect(router.state.location.pathname).toBe("/documents/new");
  });
});
