import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

const USER = "0192f5c4-0000-7000-8000-000000000002"; // the signed-in user in tests

describe("settings navigation", () => {
  it("owners see settings; accountants do not", async () => {
    server.use(http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")));
    server.use(http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")));
    renderSignedIn("/");
    expect(await screen.findByRole("navigation", { name: "Settings" })).toBeInTheDocument();
  });

  it("is hidden from an accountant", async () => {
    server.use(http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")));
    server.use(http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")));
    renderSignedIn("/", { role: "ACCOUNTANT" });
    await screen.findByRole("navigation", { name: "Main" });
    expect(screen.queryByRole("navigation", { name: "Settings" })).not.toBeInTheDocument();
  });
});

describe("company", () => {
  it("saves the company details with If-Match", async () => {
    let sent: { ifMatch: string | null; body: unknown } | null = null;
    server.use(
      http.get(`${API}/tenant`, () =>
        HttpResponse.json({
          id: "t1",
          legal_name: "Nair Constructions",
          trade_name: null,
          pan: null,
          status: "ACTIVE",
          plan: "standard",
          timezone: "Asia/Kolkata",
          version: 3,
          created_at: "",
          updated_at: "",
        }),
      ),
      http.patch(`${API}/tenant`, async ({ request }) => {
        sent = { ifMatch: request.headers.get("If-Match"), body: await request.json() };
        return HttpResponse.json({
          id: "t1",
          legal_name: "Nair Constructions Pvt Ltd",
          trade_name: "Nair",
          pan: "AAACN1234A",
          status: "ACTIVE",
          plan: "standard",
          timezone: "Asia/Kolkata",
          version: 4,
          created_at: "",
          updated_at: "",
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/company");
    const legal = await screen.findByLabelText("Legal name");
    await user.clear(legal);
    await user.type(legal, "Nair Constructions Pvt Ltd");
    await user.type(screen.getByLabelText("Trade name"), "Nair");
    await user.type(screen.getByLabelText("PAN"), "aaacn1234a");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(sent).toEqual({
      ifMatch: '"v3"',
      body: { legal_name: "Nair Constructions Pvt Ltd", trade_name: "Nair", pan: "AAACN1234A" },
    });
  });
});

describe("members", () => {
  const members = [
    {
      id: "m1",
      user_id: USER,
      email: "asha@x.in",
      full_name: "Asha Nair",
      role: "OWNER",
      status: "ACTIVE",
      invited_by: null,
      created_at: "",
    },
    {
      id: "m2",
      user_id: "u2",
      email: "ravi@x.in",
      full_name: "Ravi",
      role: "ACCOUNTANT",
      status: "ACTIVE",
      invited_by: null,
      created_at: "",
    },
  ];

  it("invites, explains a missing account, changes a role and removes", async () => {
    const calls: string[] = [];
    server.use(
      http.get(`${API}/members`, () => HttpResponse.json({ results: members })),
      http.post(`${API}/members`, async ({ request }) => {
        const body = (await request.json()) as { email: string; role: string };
        calls.push(`invite ${body.email} ${body.role}`);
        return body.email === "new@x.in"
          ? HttpResponse.json(
              {
                type: "/errors/validation_error",
                title: "Validation failed",
                status: 422,
                code: "validation_error",
                detail: "1 field is invalid.",
                errors: [
                  { field: "email", code: "no_account", message: "No account with this email." },
                ],
              },
              { status: 422 },
            )
          : HttpResponse.json(members[1], { status: 201 });
      }),
      http.patch(`${API}/members/m2`, async ({ request }) => {
        calls.push(`role ${JSON.stringify(await request.json())}`);
        return HttpResponse.json({ ...members[1], role: "VIEWER" });
      }),
      http.delete(`${API}/members/m2`, () => {
        calls.push("remove");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderSignedIn("/settings/members");
    const self = (await screen.findByText("(you)")).closest("tr") as HTMLElement;
    expect(within(self).queryByRole("combobox")).not.toBeInTheDocument(); // not your own role
    expect(within(self).queryByRole("button")).not.toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Invite member" });
    await user.type(within(form).getByLabelText("Email"), "new@x.in");
    await user.click(within(form).getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/No account uses new@x.in yet/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Role of Ravi"), "VIEWER");
    await waitFor(() => {
      expect(calls).toContain('role {"role":"VIEWER"}');
    });
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(calls).toContain("remove");
    });
    expect(calls[0]).toBe("invite new@x.in ACCOUNTANT");
  });
});

describe("invitations", () => {
  it("shows an invitation to another company and accepts it", async () => {
    let accepted = false;
    server.use(
      http.get(`${API}/invitations`, () =>
        HttpResponse.json({
          results: accepted
            ? []
            : [
                {
                  id: "inv1",
                  tenant_id: "t9",
                  legal_name: "Kochi Infra",
                  role: "VIEWER",
                  invited_by_name: "Meera",
                  invited_at: "",
                },
              ],
        }),
      ),
      http.post(`${API}/invitations/inv1/accept`, () => {
        accepted = true;
        return HttpResponse.json({ id: "t9", legal_name: "Kochi Infra", role: "VIEWER" });
      }),
      http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/parties");
    expect(await screen.findByText(/Meera invited you to/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => {
      expect(screen.queryByText(/invited you to/)).not.toBeInTheDocument();
    });
  });
});

describe("registrations and series", () => {
  it("edits a registration and a series with If-Match", async () => {
    const calls: string[] = [];
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
              version: 2,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.patch(`${API}/gst-registrations/r1`, async ({ request }) => {
        calls.push(
          `reg ${request.headers.get("If-Match") ?? ""} ${JSON.stringify(await request.json())}`,
        );
        return HttpResponse.json({});
      }),
      http.get(`${API}/document-series`, () =>
        HttpResponse.json({
          results: [
            {
              id: "s1",
              gst_registration_id: "r1",
              doc_type: "TAX_INVOICE",
              fy_start_year: 2026,
              prefix: "INV/",
              next_number: 8,
              pad_width: 4,
              next_doc_number: "INV/0008",
              is_active: true,
              version: 5,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        }),
      ),
      http.patch(`${API}/document-series/s1`, async ({ request }) => {
        calls.push(
          `series ${request.headers.get("If-Match") ?? ""} ${JSON.stringify(await request.json())}`,
        );
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/gst-registrations");
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const reg = screen.getByRole("form", { name: "Edit 32AAACN1234A1Z5" });
    await user.type(within(reg).getByLabelText("Trade name"), "Nair");
    await user.click(within(reg).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calls[0]).toContain('reg "v2"');
    });
    expect(calls[0]).toContain('"trade_name":"Nair"');
    expect(calls[0]).toContain('"state_code":"32"');

    cleanup(); // one app at a time
    renderSignedIn("/settings/series");
    const editButtons = await screen.findAllByRole("button", { name: "Edit" });
    await user.click(editButtons[0] as HTMLElement);
    const series = screen.getByRole("form", { name: "Edit series INV/0008" });
    await user.click(within(series).getByLabelText("Active"));
    await user.click(within(series).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calls[1]).toBe(
        'series "v5" {"prefix":"INV/","next_number":8,"pad_width":4,"is_active":false}',
      );
    });
  });
});
