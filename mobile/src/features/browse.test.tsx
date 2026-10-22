import { fireEvent, screen } from "@testing-library/react-native";
import { Linking } from "react-native";

import { EMPTY_RECEIVABLES, EMPTY_SUMMARY, json, on, problem } from "@/test/api";
import { CLIENT, listed, payment, PROJECT, projectReport, totals } from "@/test/fixtures";
import { renderSignedIn } from "@/test/render";

function party() {
  return {
    id: CLIENT,
    display_name: "Skyline Developers",
    legal_name: "Skyline Developers Pvt Ltd",
    is_customer: true,
    is_vendor: false,
    gst_treatment: "REGISTERED",
    gstin: "32AAACS4321K1Z5",
    pan: "AAACS4321K",
    state_code: "32",
    state_name: "Kerala",
    billing_address: null,
    email: "accounts@skyline.in",
    phone: "+919847012345",
    is_active: true,
    version: 1,
    created_at: "",
    updated_at: "",
  };
}

describe("a client", () => {
  it("opens from the dashboard: unpaid bills summed exactly, and a call button", async () => {
    const openURL = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined);
    on("GET", "/reports/summary", () => json(EMPTY_SUMMARY));
    on("GET", "/reports/receivables", () =>
      json({
        results: [
          {
            ...EMPTY_RECEIVABLES.totals,
            party_id: CLIENT,
            display_name: "Skyline Developers",
            document_count: 2,
            total: "323680.10",
          },
        ],
        totals: { ...EMPTY_RECEIVABLES.totals, total: "323680.10" },
      }),
    );
    on("GET", `/parties/${CLIENT}`, () => json(party()));
    let asked = "";
    on("GET", "/documents", (request) => {
      asked = new URL(request.url).search;
      return json({
        results: [
          listed({ totals: totals({ outstanding: "0.10" }) }),
          listed({
            id: "d2",
            doc_number: "INV/0002",
            totals: totals({ outstanding: "323680.00" }),
          }),
        ],
        next_cursor: null,
      });
    });
    await renderSignedIn("/");
    await fireEvent.press(
      await screen.findByRole("button", { name: "Skyline Developers, owes ₹3,23,680.10" }),
    );
    expect(await screen.findByText("GSTIN 32AAACS4321K1Z5")).toBeTruthy();
    expect(await screen.findByText("₹3,23,680.10")).toBeTruthy(); // 0.10 + 323680.00, in paise
    expect(asked).toContain(`party_id=${CLIENT}`);
    expect(asked).toContain("payment_state=OPEN");
    await fireEvent.press(screen.getByRole("button", { name: "Call Skyline Developers" }));
    expect(openURL).toHaveBeenCalledWith("tel:+919847012345");
  });
});

describe("projects", () => {
  it("lists margins and opens a project with its money and BOQ progress", async () => {
    on("GET", "/reports/projects", () =>
      json({
        results: [
          projectReport(),
          projectReport({
            project_id: "p2",
            code: "SCH-2",
            name: "School block",
            margin: "5000.00",
          }),
        ],
      }),
    );
    on("GET", `/projects/${PROJECT}`, () =>
      json({
        id: PROJECT,
        code: "VILLA-1",
        name: "Villa at Kakkanad",
        client_party_id: CLIENT,
        client_name: "Skyline Developers",
        gst_registration_id: "r1",
        site_address: null,
        site_state_code: "32",
        contract_value: "1140000.00",
        retention_pct: "5.00",
        income_tax_tds_pct: "1.00",
        gst_tds_applicable: false,
        mobilisation_advance: "0.00",
        advance_recovery_pct: "0.00",
        status: "ACTIVE",
        start_date: null,
        end_date: null,
        version: 1,
        created_at: "",
        updated_at: "",
      }),
    );
    on("GET", `/reports/projects/${PROJECT}`, () => json(projectReport()));
    on("GET", `/projects/${PROJECT}/boq-progress`, () =>
      json({
        results: [
          {
            boq_item_id: "b1",
            item_code: "2.1",
            description: "RCC M25",
            unit: "cum",
            rate: "6800.00",
            is_variation: false,
            contract_qty: "100.000",
            billed_qty: "42.500",
            balance_qty: "57.500",
            contract_value: "680000.00",
            billed_value: "289000.00",
            progress_pct: "42.50",
          },
        ],
        totals: { contract_value: "680000.00", billed_value: "289000.00", progress_pct: "42.50" },
      }),
    );
    await renderSignedIn("/projects");
    expect(await screen.findByText("margin -₹21,000.00")).toBeTruthy();
    expect(screen.getByText("margin ₹5,000.00")).toBeTruthy();
    await fireEvent.press(
      screen.getByRole("button", { name: "Villa at Kakkanad, ₹3,23,680.00 outstanding" }),
    );
    expect(await screen.findByText("VILLA-1 · Active · Skyline Developers")).toBeTruthy();
    expect(screen.getByText("-₹21,000.00")).toBeTruthy();
    expect(await screen.findByText("2.1 RCC M25")).toBeTruthy();
    expect(screen.getAllByText("42.5 %")).toHaveLength(2); // the item and the whole BOQ
  });

  it("explains a role without reports", async () => {
    on("GET", "/reports/projects", () => problem(403, "permission_denied"));
    await renderSignedIn("/projects", { role: "SITE_ENGINEER" });
    expect(await screen.findByText("Your role does not have access to this.")).toBeTruthy();
  });
});

describe("payments", () => {
  it("lists payments, flags what is not allocated, and opens the bills a payment settled", async () => {
    let asked = "";
    on("GET", "/payments", (request) => {
      asked = new URL(request.url).search;
      return json({
        results: [
          payment(),
          payment({ id: "pay2", party_name: "Kochi Metro", status: "VOIDED", unallocated: "0.00" }),
        ],
        next_cursor: null,
      });
    });
    on("GET", "/payments/pay1", () => json(payment()));
    on("GET", "/documents/d1", () => json({ ...listed(), notes: null, terms: null, lines: [] }));
    on("GET", "/documents/d1/allocations", () =>
      json({
        document_id: "d1",
        doc_type: "TAX_INVOICE",
        applied: null,
        unapplied: null,
        allocations: [],
      }),
    );
    await renderSignedIn("/payments");
    expect(await screen.findByText("₹50,000.00 not allocated")).toBeTruthy();
    expect(screen.getByText("Voided")).toBeTruthy();
    expect(asked).toBe("?ordering=-payment_date&limit=30");
    await fireEvent.press(
      screen.getByRole("button", { name: "Skyline Developers, ₹2,00,000.00 on 21 Oct 2026" }),
    );
    expect(await screen.findByText("21 Oct 2026 · UPI · UTR123")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "INV/0001, ₹1,50,000.00" }));
    expect(
      await screen.findByRole("header", { name: "Tax invoice INV/0001 · RA bill 1" }),
    ).toBeTruthy();
  });
});
