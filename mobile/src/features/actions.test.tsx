import { fireEvent, screen } from "@testing-library/react-native";
import { Alert } from "react-native";

import { json, on, problem } from "@/test/api";
import { CLIENT, document, listed, payment, totals } from "@/test/fixtures";
import { renderSignedIn } from "@/test/render";
import { isoDate } from "@/lib/periods";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function party() {
  return {
    id: CLIENT,
    display_name: "Skyline Developers",
    legal_name: null,
    is_customer: true,
    is_vendor: false,
    gst_treatment: "REGISTERED",
    gstin: null,
    pan: null,
    state_code: "32",
    state_name: "Kerala",
    billing_address: null,
    email: null,
    phone: null,
    is_active: true,
    version: 1,
    created_at: "",
    updated_at: "",
  };
}

/** Two unpaid bills, oldest first: ₹1,00,000.00 and ₹50,000.50 owed. */
function unpaid() {
  on("GET", `/parties/${CLIENT}`, () => json(party()));
  on("GET", "/documents", () =>
    json({
      results: [
        listed({ doc_date: "2026-09-01", totals: totals({ outstanding: "100000.00" }) }),
        listed({ id: "d2", doc_number: "INV/0002", totals: totals({ outstanding: "50000.50" }) }),
      ],
      next_cursor: null,
    }),
  );
}

describe("recording a payment", () => {
  it("spreads it over the client's bills oldest first and opens the payment", async () => {
    unpaid();
    const sent: { body: unknown; key: string | null }[] = [];
    on("POST", "/payments", async (request) => {
      sent.push({ body: await request.json(), key: request.headers.get("Idempotency-Key") });
      return json(payment({ id: "pay9", amount: "120000.00", unallocated: "0.00" }), 201);
    });
    on("GET", "/payments/pay9", () =>
      json(payment({ id: "pay9", amount: "120000.00", unallocated: "0.00" })),
    );
    await renderSignedIn(`/clients/${CLIENT}`);
    await fireEvent.press(await screen.findByRole("button", { name: "Record a payment" }));
    expect(await screen.findByRole("header", { name: "From Skyline Developers" })).toBeTruthy();

    await fireEvent.changeText(screen.getByLabelText("Amount received (₹)"), "1,20,000");
    expect(screen.getByLabelText("Amount for INV/0001").props.value).toBe("100000.00");
    expect(screen.getByLabelText("Amount for INV/0002").props.value).toBe("20000.00");
    expect(screen.getByText("Allocated ₹1,20,000.00")).toBeTruthy();
    await fireEvent.press(screen.getByRole("radio", { name: "Cheque" }));
    await fireEvent.changeText(screen.getByLabelText("Cheque number"), " 004512 ");
    await fireEvent.press(screen.getByRole("button", { name: "Record payment" }));

    expect(await screen.findByText("₹1,20,000.00")).toBeTruthy(); // the payment screen
    expect(sent).toHaveLength(1);
    expect(sent[0]?.body).toEqual({
      party_id: CLIENT,
      payment_date: isoDate(new Date()),
      amount: "120000",
      mode: "CHEQUE",
      reference: "004512",
      allocations: [
        { document_id: "d1", amount: "100000.00" },
        { document_id: "d2", amount: "20000.00" },
      ],
    });
    expect(sent[0]?.key).toMatch(UUID);
  });

  it("starts from the bill it came from, keeps the rest as an advance, and retries with the same key", async () => {
    unpaid();
    const keys: (string | null)[] = [];
    const bodies: unknown[] = [];
    on("POST", "/payments", async (request) => {
      keys.push(request.headers.get("Idempotency-Key"));
      bodies.push(await request.json());
      return new Response(
        JSON.stringify({
          type: "/errors/validation_error",
          title: "Validation failed",
          status: 422,
          code: "validation_error",
          detail: "1 field is invalid.",
          errors: [
            {
              field: "allocations[0].amount",
              code: "allocation_exceeds_outstanding",
              message: "More than INV/0002 still owes.",
            },
          ],
        }),
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      );
    });
    await renderSignedIn(`/payments/new?party=${CLIENT}&document=d2`);
    await fireEvent.changeText(await screen.findByLabelText("Amount received (₹)"), "60000");
    // INV/0002 (where the owner came from) first, then the oldest.
    expect(screen.getByLabelText("Amount for INV/0002").props.value).toBe("50000.50");
    expect(screen.getByLabelText("Amount for INV/0001").props.value).toBe("9999.50");

    await fireEvent.changeText(screen.getByLabelText("Amount for INV/0001"), "20000");
    await fireEvent.press(screen.getByRole("button", { name: "Record payment" }));
    expect(screen.getByText("The bills add up to more than the payment.")).toBeTruthy();
    expect(bodies).toHaveLength(0); // not sent

    await fireEvent.changeText(screen.getByLabelText("Amount for INV/0001"), "0");
    expect(screen.getByText("Allocated ₹50,000.50 · kept as advance ₹9,999.50")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Record payment" }));
    expect(await screen.findByText("More than INV/0002 still owes.")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Record payment" }));
    await screen.findByText("More than INV/0002 still owes.");
    expect(keys).toHaveLength(2);
    expect(keys[0]).toMatch(UUID);
    expect(keys[1]).toBe(keys[0]); // one payment, one key: a retry cannot record it twice
    expect(bodies[0]).toMatchObject({
      amount: "60000",
      mode: "UPI",
      reference: null,
      allocations: [{ document_id: "d2", amount: "50000.50" }],
    });

    await fireEvent.press(screen.getByRole("button", { name: "Fill oldest first" }));
    expect(screen.getByLabelText("Amount for INV/0001").props.value).toBe("9999.50");
  });
});

describe("issuing a draft", () => {
  function confirmWith(button: string) {
    return jest.spyOn(Alert, "alert").mockImplementation((_title, _message, buttons) => {
      buttons?.find((b) => b.text === button)?.onPress?.();
    });
  }

  function draft() {
    const d = document({ id: "d9", status: "DRAFT", doc_number: null, version: 3 });
    on("GET", "/documents/d9", () => json(d));
    on("GET", "/documents/d9/allocations", () =>
      json({
        document_id: "d9",
        doc_type: "TAX_INVOICE",
        applied: null,
        unapplied: null,
        allocations: [],
      }),
    );
    return d;
  }

  it("asks first, sends If-Match and a key, and shows the number it got", async () => {
    const d = draft();
    const alert = confirmWith("Issue");
    let headers: Record<string, string | null> = {};
    on("POST", "/documents/d9/issue", (request) => {
      headers = {
        ifMatch: request.headers.get("If-Match"),
        key: request.headers.get("Idempotency-Key"),
      };
      return json({ ...d, status: "ISSUED", doc_number: "INV/0007", version: 4 });
    });
    await renderSignedIn("/documents/d9");
    await fireEvent.press(await screen.findByRole("button", { name: "Issue" }));
    expect(
      await screen.findByRole("header", { name: "Tax invoice INV/0007 · RA bill 1" }),
    ).toBeTruthy();
    expect(alert).toHaveBeenCalledWith(
      "Issue this tax invoice?",
      "It gets the next number and can no longer be edited.",
      expect.anything(),
    );
    expect(headers.ifMatch).toBe('"v3"');
    expect(headers.key).toMatch(UUID);
    expect(screen.queryByRole("button", { name: "Issue" })).toBeNull();
    expect(screen.getByRole("button", { name: "Share PDF" })).toBeTruthy();
  });

  it("does nothing when the owner changes their mind, and explains a missing number series", async () => {
    draft();
    confirmWith("Not now");
    await renderSignedIn("/documents/d9");
    await fireEvent.press(await screen.findByRole("button", { name: "Issue" }));
    expect(screen.getByRole("button", { name: "Issue" })).toBeTruthy(); // nothing was sent

    confirmWith("Issue");
    on("POST", "/documents/d9/issue", () =>
      problem(409, "series_missing", "No active number series for tax invoices in FY 2026-27."),
    );
    await fireEvent.press(screen.getByRole("button", { name: "Issue" }));
    expect(
      await screen.findByText(
        "No active number series for tax invoices in FY 2026-27. Add a number series in the web app (Settings, Number series).",
      ),
    ).toBeTruthy();
  });
});

describe("roles", () => {
  it("shows viewers no actions", async () => {
    unpaid();
    await renderSignedIn(`/clients/${CLIENT}`, { role: "VIEWER" });
    expect(await screen.findByText("Unpaid bills")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Record a payment" })).toBeNull();
  });
});
