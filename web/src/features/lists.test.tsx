import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const page = (results: object[]) => HttpResponse.json({ results, next_cursor: null });

function payment(id: string, amount: string, unallocated: string, status = "RECORDED") {
  return {
    id,
    version: 1,
    party_id: "c1",
    party_name: `Client ${id}`,
    project_id: null,
    project_name: null,
    payment_date: "2026-10-25",
    amount,
    mode: "UPI",
    reference: null,
    notes: null,
    status,
    allocated: "0.00",
    unallocated,
    allocations: [],
    voided_at: null,
    void_reason: null,
    created_at: "",
    updated_at: "",
  };
}

describe("lists on the shared table (D.7)", () => {
  it("payments: totals leave out voided ones; sorting asks the server", async () => {
    const orderings: (string | null)[] = [];
    server.use(
      http.get(`${API}/payments`, ({ request }) => {
        orderings.push(new URL(request.url).searchParams.get("ordering"));
        return page([
          payment("a", "100000.00", "0.00"),
          payment("b", "50000.50", "5000.00"),
          payment("c", "99999.00", "99999.00", "VOIDED"),
        ]);
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/payments");
    await user.selectOptions(await screen.findByLabelText("Status"), "");
    const table = await screen.findByRole("table", { name: "Payments" });
    const totals = await within(table).findByText("Total of 2 shown, not counting voided");
    const row = totals.closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("₹1,50,000.50");
    expect(row).toHaveTextContent("₹5,000.00");
    expect(within(table).getByText("Voided")).toBeInTheDocument(); // the Status column is back
    expect(orderings.at(-1)).toBe("-payment_date");
    await user.click(within(table).getByRole("button", { name: /Amount/ }));
    await waitFor(() => {
      expect(orderings.at(-1)).toBe("amount");
    });
  });

  it("only offers 'new' buttons to roles that may use them", async () => {
    server.use(
      http.get(`${API}/payments`, () => page([])),
      http.get(`${API}/expenses`, () => page([])),
      http.get(`${API}/parties`, () => page([])),
      http.get(`${API}/projects`, () => page([])),
    );
    const router = renderSignedIn("/payments", { role: "SITE_ENGINEER" });
    expect(await screen.findByText("No payments yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Record payment" })).not.toBeInTheDocument();
    await router.navigate("/expenses");
    expect(await screen.findByText("No expenses yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Record expense" }).length).toBeGreaterThan(0);
    await router.navigate("/parties");
    expect(await screen.findByText("No clients or vendors yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New client or vendor" })).not.toBeInTheDocument();
    await router.navigate("/projects");
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New project" })).not.toBeInTheDocument();
  });

  it("projects: a total of the contract values shown", async () => {
    const project = (id: string, value: string | null) => ({
      id,
      code: id.toUpperCase(),
      name: `Site ${id}`,
      client_name: "Skyline Developers",
      site_state_code: "32",
      status: "ACTIVE",
      contract_value: value,
    });
    server.use(
      http.get(`${API}/projects`, () =>
        page([project("a", "4500000.00"), project("b", "1250000.50"), project("c", null)]),
      ),
    );
    renderSignedIn("/projects");
    const totals = await screen.findByText("Total of 2 with a contract value");
    expect(totals.closest("tr")).toHaveTextContent("₹57,50,000.50");
  });

  it("catalog: Edit opens the item in a side panel; Esc closes it", async () => {
    server.use(
      http.get(`${API}/catalog-items`, () =>
        page([
          {
            id: "c1",
            name: "OPC 53 cement",
            description: null,
            unit: "bag",
            sac_hsn: "2523",
            default_rate: "380.00",
            gst_rate: "28.00",
            variants: [],
            last_used_at: null,
            is_active: true,
            version: 1,
            created_at: "",
            updated_at: "",
          },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/catalog");
    await user.click(await screen.findByRole("button", { name: "Edit OPC 53 cement" }));
    const panel = await screen.findByRole("dialog", { name: "Edit OPC 53 cement" });
    expect(within(panel).getByDisplayValue("OPC 53 cement")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Close" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
