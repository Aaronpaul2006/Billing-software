import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";

describe("TDS certificates", () => {
  it("lists, adds (a duplicate is explained) and deletes certificates", async () => {
    const calls: string[] = [];
    server.use(
      http.get(`${API}/tds-certificates`, () =>
        HttpResponse.json({
          results: [
            {
              id: "c1",
              version: 1,
              party_id: CLIENT,
              party_name: "Skyline Developers",
              deductor_tan: "BLRS12345E",
              section: "194C",
              fy_start_year: 2026,
              quarter: 3,
              certificate_number: "QWERTYU",
              certificate_date: "2027-02-10",
              amount_credited: null,
              tds_amount: "5000.00",
              notes: null,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.get(`${API}/parties`, () =>
        HttpResponse.json({
          results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
          next_cursor: null,
        }),
      ),
      http.post(`${API}/tds-certificates`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        calls.push(`add ${JSON.stringify(body)}`);
        return calls.length === 1
          ? problem(409, "certificate_exists", "Already recorded.")
          : HttpResponse.json(body, { status: 201 });
      }),
      http.delete(`${API}/tds-certificates/c1`, () => {
        calls.push("delete");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderSignedIn("/tds-certificates");
    const row = (await screen.findByText("QWERTYU")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Skyline Developers")).toBeInTheDocument();
    expect(within(row).getByText("₹5,000.00")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add certificate" }));
    const form = screen.getByRole("form", { name: "New TDS certificate" });
    await user.type(within(form).getByLabelText("Client"), "sky");
    await user.click(await within(form).findByRole("button", { name: /Skyline Developers/ }));
    await user.type(within(form).getByLabelText("Client's TAN"), "blrs12345e");
    await user.selectOptions(within(form).getByLabelText("Quarter"), "3");
    await user.type(within(form).getByLabelText("Certificate number"), "QWERTYU");
    await user.type(within(form).getByLabelText("TDS deducted (₹)"), "780");
    await user.click(within(form).getByRole("button", { name: "Add certificate" }));
    expect(await screen.findByText(/already recorded/)).toBeInTheDocument();
    expect(calls[0]).toContain('"deductor_tan":"BLRS12345E"');
    expect(calls[0]).toContain('"quarter":3');
    expect(calls[0]).toContain('"tds_amount":"780"');

    await user.click(screen.getByRole("button", { name: "Delete certificate QWERTYU" }));
    await waitFor(() => {
      expect(calls).toContain("delete");
    });
  });
});
