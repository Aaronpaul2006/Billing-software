import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { browser, polling } from "@/features/exports/exports";
import { periodRange } from "@/features/dashboard/periods";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const ID = "0192f5c4-0000-7000-8000-0000000000c1";

function entry(over: Record<string, unknown>) {
  return {
    date: "2026-10-19",
    kind: "TAX_INVOICE",
    reference: "INV/0001",
    description: "Tax invoice INV/0001 (less retention 14450.00 and TDS 2890.00)",
    debit: "323680.00",
    credit: "0.00",
    balance: "223680.00",
    document_id: "d1",
    payment_id: null,
    retention_release_id: null,
    ...over,
  };
}

function statement(query: URLSearchParams) {
  return {
    party: { id: ID, display_name: "Skyline Developers", gstin: "32AAACS4321K1Z5" },
    from: query.get("from"),
    to: query.get("to"),
    opening_balance: "0.00",
    entries: [
      entry({
        date: "2026-10-01",
        kind: "PAYMENT",
        reference: "ADV-1",
        description: "Payment received · Bank transfer · ADV-1",
        debit: "0.00",
        credit: "100000.00",
        balance: "-100000.00",
        document_id: null,
        payment_id: "p1",
      }),
      entry({}),
    ],
    total_debit: "323680.00",
    total_credit: "100000.00",
    closing_balance: "223680.00",
  };
}

const exported = {
  id: "x1",
  kind: "STATEMENT",
  format: "PDF",
  params: {},
  status: "PENDING",
  file_name: null,
  size_bytes: null,
  row_count: null,
  warnings: [],
  error: null,
  created_at: "2026-10-22T10:00:00Z",
  finished_at: null,
  download_url: null,
};

describe("statement of account", () => {
  beforeEach(() => {
    polling.delayMs = 0;
  });

  it("shows the running balance, changes period, and downloads a PDF", async () => {
    const asked: string[] = [];
    let sent: { body: unknown; key: string | null } | null = null;
    server.use(
      http.get(`${API}/parties/${ID}/statement`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        asked.push(`${q.get("from") ?? ""}..${q.get("to") ?? ""}`);
        return HttpResponse.json(statement(q));
      }),
      http.post(`${API}/exports`, async ({ request }) => {
        sent = { body: await request.json(), key: request.headers.get("Idempotency-Key") };
        return HttpResponse.json(exported, { status: 202 });
      }),
      http.get(`${API}/exports/x1`, () =>
        HttpResponse.json({
          ...exported,
          status: "READY",
          file_name: "statement.pdf",
          download_url: "https://storage.example.test/statement.pdf",
        }),
      ),
    );
    const opened: string[] = [];
    vi.spyOn(browser, "open").mockImplementation((url) => {
      opened.push(url);
    });
    const user = userEvent.setup();
    renderSignedIn(`/parties/${ID}/statement`);

    const table = await screen.findByRole("table", { name: "Statement" });
    expect(within(table).getByText("Opening balance")).toBeInTheDocument();
    expect(within(table).getByText("-₹1,00,000.00")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: /Tax invoice INV\/0001/ })).toHaveAttribute(
      "href",
      "/documents/d1",
    );
    expect(within(table).getByRole("link", { name: /ADV-1/ })).toHaveAttribute(
      "href",
      "/payments/p1",
    );
    expect(screen.getByText(/due from the client/)).toBeInTheDocument();
    const fy = periodRange("this_fy", new Date());
    expect(asked[0]).toBe(`${fy.from}..${fy.to}`);

    await user.selectOptions(screen.getByLabelText("Period"), "last_fy");
    const last = periodRange("last_fy", new Date());
    await waitFor(() => {
      expect(asked.at(-1)).toBe(`${last.from}..${last.to}`);
    });

    await user.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() => {
      expect(opened).toEqual(["https://storage.example.test/statement.pdf"]);
    });
    expect(sent).toEqual({
      body: {
        kind: "STATEMENT",
        format: "PDF",
        params: { party_id: ID, from: last.from, to: last.to },
      },
      key: expect.stringMatching(/^[0-9a-f-]{36}$/) as unknown,
    });
  });

  it("explains a file that could not be made", async () => {
    server.use(
      http.get(`${API}/parties/${ID}/statement`, ({ request }) =>
        HttpResponse.json(statement(new URL(request.url).searchParams)),
      ),
      http.post(`${API}/exports`, () =>
        HttpResponse.json(
          { ...exported, status: "FAILED", error: "The file could not be made." },
          { status: 202 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn(`/parties/${ID}/statement`);
    await screen.findByRole("table", { name: "Statement" });
    await user.click(screen.getByRole("button", { name: "Excel" }));
    expect(await screen.findByText("The file could not be made.")).toBeInTheDocument();
  });
});
