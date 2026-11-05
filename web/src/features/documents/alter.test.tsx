import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { doc, DOC, useDoc } from "@/test/documents";
import { chooseMore } from "@/test/menu";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function editor() {
  server.use(
    http.get(`${API}/documents/copy`, () => HttpResponse.json(doc({ id: "copy" }))),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/projects/:id/boq-items`, () =>
      HttpResponse.json({ results: [], next_cursor: null }),
    ),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/documents:preview-totals`, () =>
      HttpResponse.json({ place_of_supply: "32", supply_type: "INTRA_STATE", lines: [] }),
    ),
  );
}

describe("duplicate and alter", () => {
  it("duplicates a bill into a new draft dated today", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    editor();
    const sent: { date?: string; key?: string | null } = {};
    server.use(
      http.post(`${API}/documents/${DOC}/duplicate`, async ({ request }) => {
        sent.date = ((await request.json()) as { doc_date: string }).doc_date;
        sent.key = request.headers.get("Idempotency-Key");
        return HttpResponse.json(doc({ id: "copy" }), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${DOC}`);
    await chooseMore(user, "Duplicate");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/documents/copy/edit");
    });
    expect(sent.date).toMatch(/^\d{4}-\d{2}-\d{2}$/); // today, sent explicitly
    expect(sent.key).toBeTruthy();
  });

  it("Alter explains the choices; a credit note reduces the bill", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    editor();
    let credited = false;
    server.use(
      http.post(`${API}/documents/${DOC}/credit-notes`, () => {
        credited = true;
        return HttpResponse.json(doc({ id: "copy", doc_type: "CREDIT_NOTE" }), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Alter…" }));
    const panel = screen.getByRole("region", { name: "Alter this bill" });
    expect(within(panel).getByRole("heading", { name: "Reduce the amount" })).toBeVisible();
    expect(within(panel).getByRole("heading", { name: "Increase the amount" })).toBeVisible();
    expect(within(panel).getByRole("heading", { name: "Start again" })).toBeVisible();
    await user.click(within(panel).getByRole("button", { name: "Make a credit note" }));
    await waitFor(() => {
      expect(credited).toBe(true);
    });
  });

  it("cancels with a reason and opens a corrected copy", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    editor();
    const calls: string[] = [];
    server.use(
      http.post(`${API}/documents/${DOC}/cancel`, async ({ request }) => {
        calls.push(`cancel:${JSON.stringify(await request.json())}`);
        return HttpResponse.json(doc({ status: "CANCELLED", doc_number: "INV/0001", version: 2 }));
      }),
      http.post(`${API}/documents/${DOC}/duplicate`, () => {
        calls.push("duplicate");
        return HttpResponse.json(doc({ id: "copy" }), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const router = renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Alter…" }));
    const form = screen.getByRole("form", { name: "Cancel document" });
    await user.type(within(form).getByLabelText("Reason"), "Wrong client");
    await user.click(
      within(form).getByRole("button", { name: "Cancel and make a corrected copy" }),
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/documents/copy/edit");
    });
    expect(calls).toEqual(['cancel:{"reason":"Wrong client"}', "duplicate"]);
  });

  it("a bill of supply can only start again; notes are not duplicated or altered", async () => {
    useDoc(doc({ status: "ISSUED", doc_type: "BILL_OF_SUPPLY", doc_number: "BOS/0001" }));
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Alter…" }));
    const panel = screen.getByRole("region", { name: "Alter this bill" });
    expect(within(panel).queryByRole("button", { name: "Make a credit note" })).toBeNull();
    expect(within(panel).getByRole("heading", { name: "Start again" })).toBeVisible();
  });

  it("an issued credit note has neither Duplicate nor Alter", async () => {
    useDoc(doc({ status: "ISSUED", doc_type: "CREDIT_NOTE", doc_number: "CN/0001" }));
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "More" }));
    expect(await screen.findByRole("menuitem", { name: "Cancel document…" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Duplicate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Alter…" })).toBeNull();
  });
});
