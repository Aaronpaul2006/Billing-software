import { fireEvent, screen } from "@testing-library/react-native";
import * as Sharing from "expo-sharing";

import { json, on, problem } from "@/test/api";
import { document, line, listed, payment, totals } from "@/test/fixtures";
import { renderSignedIn } from "@/test/render";

jest.mock("expo-sharing", () => ({
  isAvailableAsync: jest.fn(() => Promise.resolve(true)),
  shareAsync: jest.fn(() => Promise.resolve()),
}));

const downloaded: { url: string; uri: string }[] = [];
jest.mock("expo-file-system", () => {
  class File {
    uri: string;
    constructor(dir: { uri: string }, name: string) {
      this.uri = `${dir.uri}/${name}`;
    }
    static downloadFileAsync(url: string, target: File) {
      downloaded.push({ url, uri: target.uri });
      return Promise.resolve(target);
    }
  }
  return { File, Paths: { cache: { uri: "file:///cache" } } };
});

const EMPTY = { results: [], next_cursor: null };

describe("bills", () => {
  it("lists unpaid bills oldest first, loads more, and opens one", async () => {
    const asked: string[] = [];
    on("GET", "/documents", (request) => {
      const q = new URL(request.url).searchParams;
      asked.push(q.toString());
      if (q.get("cursor") === "c2") {
        return json({
          results: [listed({ id: "d3", doc_number: "INV/0003", party_name: "Kochi Metro" })],
          next_cursor: null,
        });
      }
      return json({
        results: [
          listed({ due_date: "2026-01-01" }), // past due
          listed({
            id: "d2",
            doc_number: "INV/0002",
            totals: totals({ amount_settled: "100000.00", outstanding: "223680.00" }),
          }),
        ],
        next_cursor: "c2",
      });
    });
    on("GET", "/documents/d1", () => json(document()));
    on("GET", "/documents/d1/allocations", () =>
      json({
        document_id: "d1",
        doc_type: "TAX_INVOICE",
        applied: null,
        unapplied: null,
        allocations: [],
      }),
    );
    await renderSignedIn("/bills");

    expect(await screen.findByText("INV/0001")).toBeTruthy();
    expect(screen.getByText("Overdue")).toBeTruthy();
    expect(screen.getByText("Part paid")).toBeTruthy();
    expect(screen.getByText("₹2,23,680.00 due")).toBeTruthy();
    expect(asked[0]).toBe(
      "status=ISSUED&doc_type=TAX_INVOICE%2CBILL_OF_SUPPLY%2CDEBIT_NOTE&payment_state=OPEN" +
        "&ordering=doc_date%2Cdoc_number&limit=30",
    );

    await fireEvent.press(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("INV/0003")).toBeTruthy();
    expect(asked[1]).toContain("cursor=c2");

    await fireEvent.press(screen.getByRole("button", { name: "INV/0001, Skyline Developers" }));
    expect(
      await screen.findByRole("header", { name: "Tax invoice INV/0001 · RA bill 1" }),
    ).toBeTruthy();
  });

  it("shows drafts, and searches by number", async () => {
    const asked: string[] = [];
    on("GET", "/documents", (request) => {
      asked.push(new URL(request.url).search);
      return json(EMPTY);
    });
    await renderSignedIn("/bills");
    expect(await screen.findByText("Nothing unpaid.")).toBeTruthy();
    await fireEvent.press(screen.getByRole("radio", { name: "Drafts" }));
    expect(await screen.findByText("No drafts.")).toBeTruthy();
    expect(asked.at(-1)).toBe("?status=DRAFT&ordering=-created_at&limit=30");
    await fireEvent.changeText(screen.getByLabelText("Search by number"), " INV/9 ");
    await fireEvent(screen.getByLabelText("Search by number"), "submitEditing");
    expect(await screen.findByText("Nothing found for “INV/9”.")).toBeTruthy();
    expect(asked.at(-1)).toContain("q=INV%2F9");
  });
});

describe("a bill", () => {
  function bill(d = document()) {
    on("GET", `/documents/${d.id}`, () => json(d));
    on("GET", `/documents/${d.id}/allocations`, () =>
      json({
        document_id: d.id,
        doc_type: d.doc_type,
        applied: null,
        unapplied: null,
        allocations: payment().allocations,
      }),
    );
  }

  it("shows the amounts that apply, the RA quantities, and who settled it", async () => {
    bill(
      document({
        totals: totals({ amount_settled: "150000.00", outstanding: "173680.00" }),
        lines: [line({ prev_cumulative_qty: "10.000", up_to_date_qty: "52.500" })],
      }),
    );
    on("GET", "/payments/pay1", () => json(payment()));
    await renderSignedIn("/documents/d1");
    expect(await screen.findByText("₹3,41,020.00")).toBeTruthy(); // total
    expect(screen.getByText("Less retention")).toBeTruthy();
    expect(screen.getByText("Less income-tax TDS")).toBeTruthy();
    expect(screen.queryByText("IGST")).toBeNull(); // ₹0.00 rows are left out
    expect(screen.queryByText("Less GST TDS")).toBeNull();
    expect(screen.getByText("₹3,23,680.00")).toBeTruthy(); // net receivable
    expect(screen.getByText("₹1,73,680.00")).toBeTruthy(); // outstanding
    expect(screen.getByText("Previous 10 · up to date 52.5 cum")).toBeTruthy();
    expect(screen.getByText("42.5 cum × ₹6,800.00 · GST 18 %")).toBeTruthy();

    await fireEvent.press(
      await screen.findByRole("button", { name: "Payment ₹1,50,000.00 on 21 Oct 2026" }),
    );
    expect(await screen.findByText("₹2,00,000.00")).toBeTruthy();
    expect(screen.getByText("₹50,000.00")).toBeTruthy(); // not allocated
  });

  it("shares the PDF through the share sheet", async () => {
    bill();
    on("GET", "/documents/d1/pdf", (request) => {
      expect(new URL(request.url).searchParams.get("as")).toBe("link");
      return json({ url: "https://storage.example.test/inv-0001.pdf?sig=1", expires_in: 300 });
    });
    await renderSignedIn("/documents/d1");
    await fireEvent.press(await screen.findByRole("button", { name: "Share PDF" }));
    await screen.findByRole("button", { name: "Share PDF" });
    expect(downloaded.at(-1)).toEqual({
      url: "https://storage.example.test/inv-0001.pdf?sig=1",
      uri: "file:///cache/INV-0001.pdf",
    });
    expect(Sharing.shareAsync).toHaveBeenCalledWith("file:///cache/INV-0001.pdf", {
      mimeType: "application/pdf",
      UTI: "com.adobe.pdf",
      dialogTitle: "INV/0001",
    });
  });

  it("says when the PDF is still being made", async () => {
    bill();
    on("GET", "/documents/d1/pdf", () => json({ status: "rendering" }, 202));
    await renderSignedIn("/documents/d1");
    await fireEvent.press(await screen.findByRole("button", { name: "Share PDF" }));
    expect(
      await screen.findByText("The PDF is still being made. Try again in a moment."),
    ).toBeTruthy();
  });

  it("has no PDF button for a draft", async () => {
    bill(document({ id: "d9", status: "DRAFT", doc_number: null }));
    await renderSignedIn("/documents/d9");
    expect(
      await screen.findByRole("header", { name: "Tax invoice (draft) · RA bill 1" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Share PDF" })).toBeNull();
  });

  it("explains a bill it cannot find", async () => {
    on("GET", "/documents/gone", () => problem(404, "not_found"));
    await renderSignedIn("/documents/gone");
    expect(
      await screen.findByText("Not found. It may have been removed, or belong to another company."),
    ).toBeTruthy();
  });
});
