import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CLIENT, doc, DOC, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Sent = { lines?: Record<string, unknown>[] };

function base(previews: Sent[] = [], terms: number | null = null) {
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/parties/${CLIENT}`, () =>
      HttpResponse.json({
        id: CLIENT,
        display_name: "Skyline Developers",
        payment_terms_days: terms,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/documents:preview-totals`, async ({ request }) => {
      previews.push((await request.json()) as Sent);
      return problem(422, "validation_error");
    }),
  );
}

async function chooseClient(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Client"), "sky");
  await user.click(await screen.findByRole("button", { name: /Skyline Developers/ }));
}

async function fillLine(
  user: ReturnType<typeof userEvent.setup>,
  n: number,
  description: string,
  qty: string,
  rate: string,
) {
  const line = screen.getByRole("group", { name: `Line ${String(n)}` });
  await user.type(within(line).getByLabelText("Description"), description);
  await user.type(within(line).getByLabelText("Quantity"), qty);
  await user.type(within(line).getByLabelText("Rate (₹)"), rate);
  return line;
}

describe("discounts and bulk edits", () => {
  it("sends a discount as a percentage when % is chosen", async () => {
    const previews: Sent[] = [];
    base(previews);
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await chooseClient(user);
    const line = await fillLine(user, 1, "Tiling", "10", "1000");
    await user.type(within(line).getByLabelText("Discount"), "10");
    await user.selectOptions(within(line).getByLabelText("Discount of line 1 in"), "pct");
    await waitFor(() => {
      expect(previews.at(-1)?.lines?.[0]).toMatchObject({ discount_pct: "10" });
    });
    expect(previews.at(-1)?.lines?.[0]).not.toHaveProperty("discount_amount");
  });

  it("changes the discount or GST of selected lines together", async () => {
    base();
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await chooseClient(user);
    await fillLine(user, 1, "Tiling", "10", "1000");
    await user.click(screen.getByRole("button", { name: "Add line" }));
    await fillLine(user, 2, "Grouting", "5", "200");

    await user.click(screen.getByLabelText(/Select all lines/));
    const bar = screen.getByRole("group", { name: "Change selected lines" });
    expect(within(bar).getByText("2 lines selected:")).toBeInTheDocument();
    await user.selectOptions(within(bar).getByLabelText("What to change"), "discount_pct");
    await user.type(within(bar).getByLabelText("New value"), "5");
    await user.click(within(bar).getByRole("button", { name: "Apply to selected" }));
    for (const n of [1, 2]) {
      const line = screen.getByRole("group", { name: `Line ${String(n)}` });
      expect(within(line).getByLabelText("Discount")).toHaveValue("5");
      expect(within(line).getByLabelText(`Discount of line ${String(n)} in`)).toHaveValue("pct");
    }

    await user.click(within(bar).getByRole("button", { name: "Clear selection" }));
    await user.click(screen.getByLabelText("Select line 2"));
    const one = screen.getByRole("group", { name: "Change selected lines" });
    await user.selectOptions(within(one).getByLabelText("What to change"), "gst_rate");
    await user.type(within(one).getByLabelText("New value"), "12");
    await user.click(within(one).getByRole("button", { name: "Apply to selected" }));
    expect(
      within(screen.getByRole("group", { name: "Line 2" })).getByLabelText("GST %"),
    ).toHaveValue("12");
    expect(
      within(screen.getByRole("group", { name: "Line 1" })).getByLabelText("GST %"),
    ).toHaveValue("");
  });

  it("shows a saved percentage discount as a percentage", async () => {
    base();
    const base_ = doc();
    const first = base_.lines[0];
    if (!first) throw new Error("fixture");
    useDoc({ ...base_, lines: [{ ...first, discount_pct: "7.50", discount_amount: "21675.00" }] });
    renderSignedIn(`/documents/${DOC}/edit`);
    const line = await screen.findByRole("group", { name: "Line 1" });
    expect(within(line).getByLabelText("Discount")).toHaveValue("7.50");
    expect(within(line).getByLabelText("Discount of line 1 in")).toHaveValue("pct");
  });

  it("says when the due date will come from the client's payment terms", async () => {
    base([], 30);
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await chooseClient(user);
    expect(
      await screen.findByText(/due 30 days after the bill date \(the client's payment terms\)/),
    ).toBeInTheDocument();
  });
});
