import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { answerConfirm } from "@/test/confirm";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

type Expense = components["schemas"]["Expense"];

function expense(overrides: Partial<Expense> = {}): Expense {
  return {
    id: "e1",
    version: 1,
    project_id: "p1",
    project_name: "Villa at Kakkanad",
    vendor_party_id: "v1",
    vendor_name: "Coastal Cement",
    category: "MATERIAL",
    expense_date: "2026-10-20",
    description: "100 bags OPC 53",
    vendor_bill_number: "CC/2231",
    taxable_value: "38000.00",
    gst_amount: "10640.00",
    total_amount: "48640.00",
    itc_eligible: true,
    amount_paid: "20000.00",
    balance: "28640.00",
    payment_mode: "UPI",
    attachment_id: null,
    status: "RECORDED",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const noProjects = () => {
  server.use(
    http.get(`${API}/projects`, () =>
      HttpResponse.json({
        results: [{ id: "p1", code: "VILLA-1", name: "Villa" }],
        next_cursor: null,
      }),
    ),
  );
};

describe("expenses", () => {
  it("lists expenses with vendor, project and what is left to pay", async () => {
    const seen: string[] = [];
    server.use(
      http.get(`${API}/expenses`, ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ results: [expense()], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/expenses");
    const row = (await screen.findByRole("link", { name: "100 bags OPC 53" })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(row).getByText("Coastal Cement")).toBeInTheDocument();
    expect(within(row).getByText("Villa at Kakkanad")).toBeInTheDocument();
    expect(within(row).getByText("₹28,640.00")).toBeInTheDocument();
    expect(within(row).getByText("ITC")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Category"), "LABOUR");
    await waitFor(() => {
      expect(seen.at(-1)).toContain("category=LABOUR");
    });
    expect(seen.at(-1)).toContain("status=RECORDED");
  });

  it("records an expense: total shown while typing, the payment mode only when paid", async () => {
    noProjects();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${API}/expenses`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(expense(), { status: 201 });
      }),
      http.get(`${API}/expenses`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/expenses/new");
    await user.type(await screen.findByLabelText("Description"), "Masons, week 42");
    await user.selectOptions(screen.getByLabelText("Category"), "LABOUR");
    await user.type(screen.getByLabelText("Amount before GST (₹)"), "42,000");
    expect(screen.getByText("₹42,000.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Paid by")).toBeDisabled();
    await user.type(screen.getByLabelText("Paid so far (₹)"), "42000");
    await user.selectOptions(screen.getByLabelText("Paid by"), "CASH");
    await user.click(screen.getByRole("button", { name: "Record expense" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/expenses");
    });
    expect(body).toMatchObject({
      category: "LABOUR",
      description: "Masons, week 42",
      project_id: null,
      vendor_party_id: null,
      taxable_value: "42000",
      gst_amount: "0",
      amount_paid: "42000",
      payment_mode: "CASH",
      itc_eligible: false,
    });
  });

  it("edits with If-Match and voids", async () => {
    noProjects();
    const calls: string[] = [];
    server.use(
      http.get(`${API}/expenses/e1`, () => HttpResponse.json(expense())),
      http.patch(`${API}/expenses/e1`, async ({ request }) => {
        const b = (await request.json()) as Record<string, unknown>;
        calls.push(`patch ${request.headers.get("If-Match") ?? ""} ${String(b.amount_paid)}`);
        return HttpResponse.json(expense({ version: 2 }));
      }),
      http.post(`${API}/expenses/e1/void`, ({ request }) => {
        calls.push(`void ${request.headers.get("If-Match") ?? ""}`);
        return HttpResponse.json(expense({ status: "VOIDED" }));
      }),
      http.get(`${API}/expenses`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/expenses/e1");
    const paid = await screen.findByLabelText("Paid so far (₹)");
    expect(paid).toHaveValue("20000.00");
    expect(screen.getByLabelText("Vendor")).toHaveValue("Coastal Cement");
    await user.clear(paid);
    await user.type(paid, "48640");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(calls).toContain('patch "v1" 48640');
    });

    renderSignedIn("/expenses/e1");
    await user.click(
      (await screen.findAllByRole("button", { name: "Void expense" }))[0] as HTMLElement,
    );
    await answerConfirm(user, "Void expense");
    await waitFor(() => {
      expect(calls).toContain('void "v1"');
    });
  });
});
