import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AUTOSAVE } from "@/features/documents/autosave";
import { CLIENT, doc, DOC, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

function base() {
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
  );
}

beforeEach(() => {
  AUTOSAVE.enabled = true;
  AUTOSAVE.delayMs = 150;
});

afterEach(() => {
  AUTOSAVE.delayMs = 2000;
});

describe("drafts save themselves", () => {
  it("creates the draft once it can be saved, then keeps it up to date", async () => {
    base();
    const created = doc({ project_id: null, project_name: null });
    useDoc(created);
    const posts: unknown[] = [];
    const patches: { body: unknown; ifMatch: string | null }[] = [];
    server.use(
      http.post(`${API}/documents`, async ({ request }) => {
        posts.push(await request.json());
        return HttpResponse.json(created, { status: 201 });
      }),
      http.patch(`${API}/documents/${DOC}`, async ({ request }) => {
        patches.push({ body: await request.json(), ifMatch: request.headers.get("If-Match") });
        return HttpResponse.json({ ...created, version: created.version + patches.length });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.type(await screen.findByLabelText("Client"), "sky");
    await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
    // a client alone is not saved: no empty drafts
    expect(
      await screen.findByText("Not saved yet: choose the client and fill in each line's quantity."),
    ).toBeInTheDocument();
    const line = screen.getByRole("group", { name: "Line 1" });
    await user.type(within(line).getByLabelText("Description"), "RCC work");
    await user.type(within(line).getByLabelText("Quantity"), "10");
    await user.type(within(line).getByLabelText("Rate (₹)"), "6800");

    await waitFor(() => {
      expect(window.location.pathname).toBe(`/documents/${DOC}/edit`); // edited in place
    });
    expect(posts).toHaveLength(1); // created once, not once per keystroke
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/Saved at/);
    });

    // a later change updates the same draft, with its version
    const again = await screen.findByRole("group", { name: "Line 1" });
    await user.clear(within(again).getByLabelText("Quantity"));
    await user.type(within(again).getByLabelText("Quantity"), "12");
    await waitFor(() => {
      expect(patches.length).toBeGreaterThan(0);
    });
    expect(patches.at(-1)?.ifMatch).toBe('"v1"');
    expect(JSON.stringify(patches.at(-1)?.body)).toContain('"quantity":"12"');
    expect(posts).toHaveLength(1);
  });

  it("stops and says so when someone else changed the draft", async () => {
    base();
    useDoc(doc());
    server.use(
      http.patch(`${API}/documents/${DOC}`, () =>
        problem(412, "stale_version", "Changed by someone else."),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}/edit`);
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.clear(within(line).getByLabelText("Quantity"));
    await user.type(within(line).getByLabelText("Quantity"), "50");
    expect(
      await screen.findByText(
        "Someone else changed this draft. Reload the page to see their version.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the server's reason, and tries again after the next change", async () => {
    base();
    useDoc(doc());
    let calls = 0;
    server.use(
      http.patch(`${API}/documents/${DOC}`, () => {
        calls += 1;
        return calls === 1
          ? problem(422, "validation_error", "The rate is too high.")
          : HttpResponse.json({ ...doc(), version: 2 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}/edit`);
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.clear(within(line).getByLabelText("Rate (₹)"));
    await user.type(within(line).getByLabelText("Rate (₹)"), "999999");
    expect(await screen.findByText("Not saved: The rate is too high.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 400));
    expect(calls).toBe(1); // not retried in a loop
    await user.clear(within(line).getByLabelText("Rate (₹)"));
    await user.type(within(line).getByLabelText("Rate (₹)"), "7000");
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/Saved at/);
    });
    expect(calls).toBe(2);
  });
});
