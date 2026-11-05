import { screen, within } from "@testing-library/react";

import { doc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

describe("bills list on a phone (D.4)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows cards with the status and the amounts, nothing cut off", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: false, // narrower than 1024 px
      media: q,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    const issued = doc({
      status: "ISSUED",
      doc_number: "INV/0002",
      totals: { ...doc().totals, outstanding: "186310.18", amount_settled: "200000.00" },
    });
    server.use(
      http.get(`${API}/documents`, () =>
        HttpResponse.json({ results: [issued], next_cursor: null }),
      ),
    );
    renderSignedIn("/documents");
    const list = await screen.findByRole("list", { name: "Bills and quotations" });
    const link = await within(list).findByRole("link", { name: "INV/0002" });
    const card = link.closest("li") as HTMLElement;
    expect(within(card).getByText("Part paid")).toBeInTheDocument();
    expect(within(card).getByText("Outstanding")).toBeInTheDocument();
    expect(within(card).getByText("₹1,86,310.18")).toBeInTheDocument();
  });
});
