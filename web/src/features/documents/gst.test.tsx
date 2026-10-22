import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

type Preview = components["schemas"]["Preview"];
type Totals = components["schemas"]["Totals"];

const SEZ = "0192f5c4-0000-7000-8000-0000000000e1";

function totals(over: Partial<Totals> = {}): Totals {
  return {
    subtotal: "68000.00",
    cgst: "0.00",
    sgst: "0.00",
    igst: "0.00",
    cess: "0.00",
    round_off: "0.00",
    grand_total: "68000.00",
    retention: "0.00",
    income_tax_tds: "0.00",
    gst_tds: "0.00",
    advance_recovery: "0.00",
    net_receivable: "68000.00",
    outstanding: "68000.00",
    ...over,
  };
}

function preview(over: Partial<Preview>): Preview {
  return {
    place_of_supply: "32",
    supply_type: "INTER_STATE",
    supply_category: "REGULAR",
    lut: false,
    reverse_charge: false,
    totals: totals(),
    lines: [],
    ...over,
  };
}

function editorMocks(answer: (body: Record<string, unknown>) => Preview) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: SEZ, display_name: "Infopark SEZ Unit", gstin: "32AAACI5555I1Z5" }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/documents:preview-totals`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      bodies.push(body);
      return HttpResponse.json(answer(body));
    }),
  );
  return bodies;
}

async function fillLine(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Client"), "info");
  await user.click(await screen.findByRole("button", { name: /Infopark SEZ Unit/ }));
  const line = screen.getByRole("group", { name: "Line 1" });
  await user.type(within(line).getByLabelText("Description"), "RCC M25");
  await user.type(within(line).getByLabelText("Quantity"), "10");
  await user.type(within(line).getByLabelText("Rate (₹)"), "6800");
  await user.type(within(line).getByLabelText("GST %"), "18");
}

describe("GST: SEZ, LUT, reverse charge", () => {
  it("an SEZ supply goes under the LUT by default, or charges IGST when chosen", async () => {
    const bodies = editorMocks((body) =>
      body.lut === false
        ? preview({
            supply_category: "SEZ",
            lut: false,
            totals: totals({
              igst: "12240.00",
              grand_total: "80240.00",
              net_receivable: "80240.00",
            }),
          })
        : preview({ supply_category: "SEZ", lut: true }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await fillLine(user);
    expect(
      await screen.findByText(
        "Supply to an SEZ unit: zero-rated under the Letter of Undertaking, no IGST.",
      ),
    ).toBeInTheDocument();
    const choice = screen.getByLabelText("Supply to an SEZ unit");
    expect(choice).toHaveValue("yes");
    expect(bodies.at(-1)?.lut).toBeNull(); // the server's default

    await user.selectOptions(choice, "no");
    expect(
      await screen.findByText("Supply to an SEZ unit: zero-rated with IGST charged."),
    ).toBeInTheDocument();
    expect(bodies.at(-1)?.lut).toBe(false);
    expect(within(screen.getByLabelText("Totals")).getByText("₹12,240.00")).toBeInTheDocument();
  });

  it("reverse charge: the tax is shown as the client's, not added to the total", async () => {
    const bodies = editorMocks((body) =>
      body.reverse_charge === true
        ? preview({
            supply_type: "INTRA_STATE",
            reverse_charge: true,
            totals: totals({ cgst: "6120.00", sgst: "6120.00" }),
          })
        : preview({ supply_type: "INTRA_STATE" }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await fillLine(user);
    await user.click(screen.getByLabelText(/Reverse charge/));
    expect(await screen.findByText("CGST (paid by the client)")).toBeInTheDocument();
    expect(
      screen.getByText("Reverse charge: the client pays the GST to the government."),
    ).toBeInTheDocument();
    expect(bodies.at(-1)?.reverse_charge).toBe(true);
    // A quotation cannot be under reverse charge: the box goes away and is not sent.
    await user.selectOptions(screen.getByLabelText("Type"), "QUOTATION");
    expect(screen.queryByLabelText(/Reverse charge/)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(bodies.at(-1)?.reverse_charge).toBe(false);
    });
  });

  it("registrations take their LUT", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/gst-registrations`, () =>
        HttpResponse.json({
          results: [
            {
              id: "r1",
              registration_type: "REGULAR",
              gstin: "32AAACN1234A1Z5",
              state_code: "32",
              state_name: "Kerala",
              legal_name: "Nair Constructions",
              trade_name: null,
              address: { line1: "MG Road", city: "Kochi", state_code: "32", pincode: "682016" },
              is_default: true,
              is_active: true,
              lut_arn: null,
              lut_fy_start_year: null,
              version: 2,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.patch(`${API}/gst-registrations/r1`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/gst-registrations");
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit 32AAACN1234A1Z5" });
    await user.type(within(form).getByLabelText("LUT ARN"), "ad32 0426 0012 34x");
    const years = within(form).getByLabelText("LUT for financial year");
    const option = within(years).getAllByRole("option")[2] as HTMLOptionElement;
    await user.selectOptions(years, option.value);
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(sent).toMatchObject({
        lut_arn: "AD320426001234X",
        lut_fy_start_year: Number(option.value),
      });
    });
  });
});
