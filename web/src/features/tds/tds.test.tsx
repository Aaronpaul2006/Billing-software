import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { answerConfirm } from "@/test/confirm";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const CLIENT = "0192f5c4-0000-7000-8000-0000000000c1";

const CERTIFICATE = {
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
};

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
    await answerConfirm(user, "Delete certificate");
    await waitFor(() => {
      expect(calls).toContain("delete");
    });
  });

  it("corrects a certificate in place", async () => {
    let saved: { body: unknown; ifMatch: string | null } | null = null;
    let certificate = CERTIFICATE;
    server.use(
      http.get(`${API}/tds-certificates`, () =>
        HttpResponse.json({ results: [certificate], next_cursor: null }),
      ),
      http.patch(`${API}/tds-certificates/c1`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        saved = { body, ifMatch: request.headers.get("If-Match") };
        certificate = { ...certificate, ...body, version: 2 };
        return HttpResponse.json(certificate);
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/tds-certificates");
    await user.click(await screen.findByRole("button", { name: "Edit certificate QWERTYU" }));
    const form = screen.getByRole("form", { name: "Edit certificate QWERTYU" });
    expect(within(form).getByLabelText("Client's TAN")).toHaveValue("BLRS12345E");
    expect(within(form).getByLabelText("Quarter")).toHaveValue("3");
    expect(within(form).getByLabelText("Certificate date")).toHaveValue("2027-02-10");
    const number = within(form).getByLabelText("Certificate number");
    await user.clear(number);
    await user.type(number, "QWERTYV");
    const amount = within(form).getByLabelText("TDS deducted (₹)");
    expect(amount).toHaveValue("5000.00");
    await user.clear(amount);
    await user.type(amount, "5,200.50");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("QWERTYV")).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(saved).toEqual({
      body: {
        party_id: CLIENT,
        deductor_tan: "BLRS12345E",
        fy_start_year: 2026,
        quarter: 3,
        certificate_number: "QWERTYV",
        certificate_date: "2027-02-10",
        amount_credited: null,
        tds_amount: "5200.50",
      },
      ifMatch: '"v1"',
    });
  });
});
