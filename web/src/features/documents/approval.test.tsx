import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DOC, doc, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function limitOf(amount: string | null) {
  server.use(
    http.get(`${API}/tenant`, () =>
      HttpResponse.json({
        id: "t1",
        legal_name: "Nair Constructions",
        trade_name: null,
        pan: null,
        status: "ACTIVE",
        plan: "FREE",
        timezone: "Asia/Kolkata",
        approval_limit: amount,
        version: 1,
        created_at: "",
        updated_at: "",
      }),
    ),
  );
}

describe("bill approval (Part B)", () => {
  it("an accountant asks for approval of a large draft", async () => {
    limitOf("100000.00");
    const draft = doc({ status: "DRAFT" });
    useDoc(draft);
    let asked = false;
    server.use(
      http.post(`${API}/documents/${DOC}/approval-request`, () => {
        asked = true;
        return HttpResponse.json({ ...draft, approval_requested_at: "2026-11-06T10:00:00Z" });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`, { role: "ACCOUNTANT" });
    expect(await screen.findByText("Needs an owner's approval")).toBeInTheDocument();
    expect(screen.getByText(/Bills of ₹1,00,000.00 or more/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ask for approval" }));
    await waitFor(() => {
      expect(asked).toBe(true);
    });
    expect(await screen.findByRole("button", { name: "Ask again" })).toBeInTheDocument();
  });

  it("an owner approves what was asked", async () => {
    limitOf("100000.00");
    const draft = doc({ status: "DRAFT", approval_requested_at: "2026-11-06T10:00:00Z" });
    useDoc(draft);
    server.use(
      http.post(`${API}/documents/${DOC}/approve`, () =>
        HttpResponse.json({
          ...draft,
          approval_holds: true,
          approved_by_name: "Aaron Paul",
          approved_at: "2026-11-06T11:00:00Z",
        }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Approve this draft" }));
    expect(await screen.findByText(/Aaron Paul approved this draft/)).toBeInTheDocument();
  });

  it("says nothing without a limit, or below it", async () => {
    limitOf(null);
    useDoc(doc({ status: "DRAFT" }));
    renderSignedIn(`/documents/${DOC}`, { role: "ACCOUNTANT" });
    expect(await screen.findByText("Place of supply")).toBeInTheDocument();
    expect(screen.queryByText("Needs an owner's approval")).not.toBeInTheDocument();
  });
});
