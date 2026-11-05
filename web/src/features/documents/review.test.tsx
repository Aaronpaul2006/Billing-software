import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { doc, DOC, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

describe("final review before issuing", () => {
  it("lists what to check, with a way to fix each, and still issues", async () => {
    useDoc(doc());
    let issued = false;
    server.use(
      http.get(`${API}/documents/${DOC}/review`, () =>
        HttpResponse.json({
          warnings: [
            {
              code: "client_no_gstin",
              message: "Skyline Developers has no GSTIN saved.",
              line_no: null,
            },
            {
              code: "rate_below_usual",
              message: 'Line 1 "RCC": rate ₹31.00 is far below the usual ₹310.00.',
              line_no: 1,
            },
          ],
        }),
      ),
      http.post(`${API}/documents/${DOC}/issue`, () => {
        issued = true;
        return HttpResponse.json(doc({ status: "ISSUED", doc_number: "INV/0001", version: 2 }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Issue…" }));
    const panel = screen.getByRole("region", { name: "Review before issuing" });
    const warnings = await within(panel).findByRole("list", { name: "Warnings" });
    const items = within(warnings).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(panel).getByText(/2 things to check/)).toBeInTheDocument();
    expect(
      within(items[0] as HTMLElement).getByRole("link", { name: "Open the client" }),
    ).toHaveAttribute("href", `/parties/${doc().party_id}`);
    expect(
      within(items[1] as HTMLElement).getByRole("link", { name: "Edit the bill" }),
    ).toHaveAttribute("href", `/documents/${DOC}/edit`);
    expect(issued).toBe(false); // nothing is issued until asked
    await user.click(within(panel).getByRole("button", { name: "Issue now" }));
    await waitFor(() => {
      expect(issued).toBe(true);
    });
  });

  it("Paid now: records the money received with the bill (Part B)", async () => {
    useDoc(doc());
    let body: unknown = null;
    server.use(
      http.post(`${API}/documents/${DOC}/issue`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(doc({ status: "ISSUED", doc_number: "INV/0001", version: 2 }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Issue…" }));
    const panel = screen.getByRole("region", { name: "Review before issuing" });
    await user.click(within(panel).getByRole("checkbox", { name: "Paid now, with the bill" }));
    // what the client owes is filled in; cash unless changed
    expect(within(panel).getByLabelText("Amount received (₹)")).toHaveValue(
      doc().totals.net_receivable,
    );
    await user.selectOptions(within(panel).getByLabelText("How"), "UPI");
    await user.type(within(panel).getByLabelText("Reference (optional)"), "UPI 4521");
    await user.click(within(panel).getByRole("button", { name: "Issue and record the payment" }));
    await waitFor(() => {
      expect(body).toEqual({
        paid_now: { amount: doc().totals.net_receivable, mode: "UPI", reference: "UPI 4521" },
      });
    });
  });

  it("Paid now is not offered on a quotation", async () => {
    useDoc(doc({ doc_type: "QUOTATION" }));
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Issue…" }));
    const panel = screen.getByRole("region", { name: "Review before issuing" });
    await within(panel).findByText("Everything looks right.");
    expect(within(panel).queryByRole("checkbox", { name: /Paid now/ })).toBeNull();
  });

  it("says when everything looks right", async () => {
    useDoc(doc());
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Issue…" }));
    expect(await screen.findByText("Everything looks right.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region", { name: "Review before issuing" })).toBeNull();
  });
});
