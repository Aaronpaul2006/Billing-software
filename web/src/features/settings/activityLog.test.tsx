import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const ENTRY = {
  id: 42,
  occurred_at: "2026-11-05T10:15:00Z",
  actor_id: "u1",
  actor_name: "Priya Nair",
  record_type: "documents",
  record_type_label: "Bill or quotation",
  record_id: "d1",
  record: "Tax invoice INV/0002",
  action: "issued",
  changed_fields: ["doc number", "issued at"],
};

function useLog() {
  const asked: URLSearchParams[] = [];
  server.use(
    http.get(`${API}/members`, () =>
      HttpResponse.json({
        results: [
          {
            id: "m1",
            user_id: "u1",
            email: "p@x.in",
            full_name: "Priya Nair",
            role: "OWNER",
            status: "ACTIVE",
            invited_by: null,
            created_at: "",
          },
        ],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/audit-log`, ({ request }) => {
      asked.push(new URL(request.url).searchParams);
      return HttpResponse.json({ results: [ENTRY], next_cursor: null });
    }),
  );
  return asked;
}

describe("activity log (Part B)", () => {
  it("shows who changed what, links the record, and filters", async () => {
    const asked = useLog();
    const user = userEvent.setup();
    renderSignedIn("/settings/activity");
    const table = await screen.findByRole("table", { name: "Activity log" });
    const link = await within(table).findByRole("link", { name: "Tax invoice INV/0002" });
    const row = link.closest("tr");
    expect(row).toHaveTextContent("Issued: doc number, issued at");
    expect(row).toHaveTextContent("Priya Nair");
    expect(within(table).getByRole("link", { name: "Tax invoice INV/0002" })).toHaveAttribute(
      "href",
      "/documents/d1",
    );
    await user.selectOptions(screen.getByLabelText("What"), "payments");
    await user.selectOptions(screen.getByLabelText("Who"), "Priya Nair");
    await waitFor(() => {
      const last = asked.at(-1);
      expect(last?.get("record_type")).toBe("payments");
      expect(last?.get("actor_id")).toBe("u1");
    });
  });

  it("is a settings tab for owners and admins only", async () => {
    server.use(
      http.get(`${API}/reports/dashboard`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
    );
    renderSignedIn("/", { role: "ACCOUNTANT" });
    await screen.findByRole("navigation", { name: "Sell" });
    expect(screen.queryByRole("link", { name: "Business settings" })).toBeNull();
  });
});

describe("invite your CA (Part B)", () => {
  it("sets the role to viewer and puts the cursor in the email box", async () => {
    server.use(
      http.get(`${API}/members`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/email-invitations`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/members");
    await user.click(await screen.findByRole("button", { name: "Invite your CA" }));
    expect(screen.getByLabelText("Role")).toHaveValue("VIEWER");
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });
});
