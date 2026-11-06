import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

function line(over: Record<string, unknown> = {}) {
  return {
    id: "l1",
    version: 1,
    account_label: "HDFC 1234",
    line_date: "2026-10-19",
    narration: "NEFT CR-SKYLINE DEVELOPERS",
    reference: "UTR778899001",
    money_in: "323680.00",
    money_out: "0.00",
    balance: null,
    status: "OPEN",
    payment_id: null,
    vendor_payment_id: null,
    note: null,
    suggestions: [
      {
        kind: "bill",
        id: "d1",
        party_id: "c1",
        party_name: "Skyline Developers",
        title: "Bill INV/0001",
        score: 60,
      },
      {
        kind: "payment",
        id: "p1",
        party_id: "c1",
        party_name: "Skyline Developers",
        title: "Payment recorded on 19 Oct",
        score: 90,
      },
    ],
    created_at: "",
    ...over,
  };
}

function useBank() {
  const posts: { url: string; body: unknown }[] = [];
  server.use(
    http.get(`${API}/bank-lines/accounts`, () => HttpResponse.json({ results: ["HDFC 1234"] })),
    http.get(`${API}/bank-lines`, () =>
      HttpResponse.json({ results: [line()], next_cursor: null }),
    ),
    http.post(`${API}/bank-lines/l1/:action`, async ({ request, params }) => {
      posts.push({ url: String(params.action), body: await request.json() });
      return HttpResponse.json(
        line({ status: params.action === "ignore" ? "IGNORED" : "MATCHED", suggestions: [] }),
      );
    }),
  );
  return posts;
}

describe("bank statements (Part B)", () => {
  it("imports a statement after showing what is in it", async () => {
    useBank();
    let imported = false;
    server.use(
      http.post(`${API}/bank-statements/preview`, () =>
        HttpResponse.json({
          ready: true,
          headers: ["Date", "Narration", "Withdrawal Amt.", "Deposit Amt."],
          columns: { date: "Date" },
          line_count: 4,
          skipped_rows: [8],
          lines: [
            {
              row: 4,
              line_date: "2026-10-19",
              narration: "NEFT CR-SKYLINE",
              reference: null,
              money_in: "323680.00",
              money_out: "0.00",
              balance: null,
            },
          ],
        }),
      ),
      http.post(`${API}/bank-statements/import`, () => {
        imported = true;
        return HttpResponse.json(
          { added: 3, duplicates: 1, skipped_rows: [8], line_count: 4 },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/bank");
    await user.click(await screen.findByRole("button", { name: "Import a statement" }));
    await user.type(screen.getByLabelText("Which account"), "HDFC 1234");
    const file = new File(["Date,Narration\n"], "statement.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("The bank's statement (CSV or Excel)"), file);
    expect(
      await screen.findByText(/4 lines found \(1 rows without a date left out/),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "First lines" })).toHaveTextContent("+₹3,23,680.00");
    await user.click(screen.getByRole("button", { name: "Import 4 lines" }));
    expect(await screen.findByText("Added 3 lines; 1 were imported before.")).toBeInTheDocument();
    expect(imported).toBe(true);
  });

  it("asks which column is which when the bank's layout is not known", async () => {
    useBank();
    // what goes into the upload: reading a multipart body back is not possible here
    const appended = vi.spyOn(FormData.prototype, "append");
    let calls = 0;
    server.use(
      http.post(`${API}/bank-statements/preview`, () => {
        calls += 1;
        return HttpResponse.json({
          ready: calls > 1,
          headers: ["When", "What", "Out", "In"],
          columns: {},
          line_count: calls > 1 ? 1 : 0,
          skipped_rows: [],
          lines: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/bank");
    await user.click(await screen.findByRole("button", { name: "Import a statement" }));
    await user.upload(
      screen.getByLabelText("The bank's statement (CSV or Excel)"),
      new File(["When,What\n"], "odd.csv", { type: "text/csv" }),
    );
    await user.selectOptions(await screen.findByLabelText("Date"), "When");
    await user.selectOptions(screen.getByLabelText("Narration / description"), "What");
    await user.selectOptions(screen.getByLabelText("Withdrawal (money out)"), "Out");
    await user.selectOptions(screen.getByLabelText("Deposit (money in)"), "In");
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText(/1 line found/)).toBeInTheDocument();
    const sent = appended.mock.calls
      .filter((c) => c[0] === "mapping")
      .map((c) => (typeof c[1] === "string" ? c[1] : ""));
    expect(JSON.parse(sent.at(-1) ?? "{}")).toEqual({
      date: "When",
      narration: "What",
      money_out: "Out",
      money_in: "In",
    });
  });

  it("matches a line to its suggestion, or records the payment for a bill", async () => {
    const posts = useBank();
    const user = userEvent.setup();
    renderSignedIn("/bank");
    await user.click(await screen.findByRole("button", { name: "Match…" }));
    const panel = await screen.findByRole("dialog", { name: "What is this line?" });
    const options = within(panel).getByRole("region", { name: "Suggestions" });
    const items = within(options).getAllByRole("listitem");
    await user.click(within(items[1] as HTMLElement).getByRole("button", { name: "This is it" }));
    await waitFor(() => {
      expect(posts).toEqual([{ url: "match", body: { payment_id: "p1" } }]);
    });
    await user.click(await screen.findByRole("button", { name: "Match…" }));
    const again = await screen.findByRole("dialog", { name: "What is this line?" });
    const bill = within(again).getAllByRole("listitem")[0] as HTMLElement;
    await user.click(within(bill).getByRole("button", { name: "Record payment for it" }));
    await waitFor(() => {
      expect(posts[1]).toEqual({
        url: "record",
        body: { party_id: "c1", allocations: [{ document_id: "d1", amount: "323680.00" }] },
      });
    });
  });

  it("ignores a line with a note", async () => {
    const posts = useBank();
    const user = userEvent.setup();
    renderSignedIn("/bank");
    await user.click(await screen.findByRole("button", { name: "Match…" }));
    const panel = await screen.findByRole("dialog", { name: "What is this line?" });
    await user.type(within(panel).getByLabelText("Why (optional)"), "bank charges");
    await user.click(within(panel).getByRole("button", { name: "Ignore this line" }));
    await waitFor(() => {
      expect(posts).toEqual([{ url: "ignore", body: { note: "bank charges" } }]);
    });
  });
});
