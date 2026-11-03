import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { doc, DOC, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

describe("change history", () => {
  it("shows who changed what, newest first, once opened", async () => {
    useDoc(doc({ status: "ISSUED", doc_number: "INV/0001" }));
    let asked = 0;
    server.use(
      http.get(`${API}/documents/${DOC}/history`, () => {
        asked += 1;
        return HttpResponse.json({
          results: [
            {
              at: "2026-11-03T10:15:00Z",
              actor_name: "Anu Accountant",
              kind: "issued",
              summary: "Issued as INV/0001",
              details: ["Total ₹3,41,020.00"],
            },
            {
              at: "2026-11-03T09:40:00Z",
              actor_name: "Ravi Nair",
              kind: "edited",
              summary: "Edited the draft",
              details: ['Line 1 "Plastering": rate ₹300.00 → ₹310.00'],
            },
            {
              at: "2026-11-02T09:00:00Z",
              actor_name: null,
              kind: "created",
              summary: "Created the draft tax invoice",
              details: [],
            },
          ],
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    const toggle = await screen.findByRole("button", { name: "Change history" });
    expect(asked).toBe(0); // not loaded until opened
    await user.click(toggle);
    const list = await screen.findByRole("list", { name: "Changes, newest first" });
    const items = within(list).getAllByRole("listitem").filter((li) => li.parentElement === list);
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Issued as INV/0001 · Anu Accountant");
    expect(items[0]).toHaveTextContent("Total ₹3,41,020.00");
    expect(items[1]).toHaveTextContent('Line 1 "Plastering": rate ₹300.00 → ₹310.00');
    expect(items[2]).toHaveTextContent("Created the draft tax invoice · System");
    expect(asked).toBe(1);
  });
});
