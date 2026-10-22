import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderApp, renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, me, problem, server, tokens } from "@/test/server";

type EmailInvitation = components["schemas"]["EmailInvitation"];

function invitation(over: Partial<EmailInvitation> = {}): EmailInvitation {
  return {
    id: "ei1",
    email: "ravi@x.in",
    role: "ACCOUNTANT",
    status: "PENDING",
    invited_by: "0192f5c4-0000-7000-8000-000000000002",
    expires_at: "2026-10-29T10:00:00Z",
    created_at: "2026-10-22T10:00:00Z",
    expired: false,
    ...over,
  };
}

function fieldProblem(field: string, code: string, message: string) {
  return HttpResponse.json(
    {
      type: "/errors/validation_error",
      title: "Validation failed",
      status: 422,
      code: "validation_error",
      detail: "1 field is invalid.",
      errors: [{ field, code, message }],
    },
    { status: 422 },
  );
}

describe("inviting someone without an account", () => {
  it("offers an invitation by email, lists it, sends again and withdraws", async () => {
    let pending: EmailInvitation[] = [];
    const calls: string[] = [];
    server.use(
      http.get(`${API}/members`, () => HttpResponse.json({ results: [] })),
      http.post(`${API}/members`, () =>
        fieldProblem("email", "no_account", "No account uses this email."),
      ),
      http.get(`${API}/email-invitations`, () => HttpResponse.json({ results: pending })),
      http.post(`${API}/email-invitations`, async ({ request }) => {
        calls.push(`invite ${JSON.stringify(await request.json())}`);
        pending = [invitation()];
        return HttpResponse.json(invitation(), { status: 201 });
      }),
      http.post(`${API}/email-invitations/ei1/resend`, () => {
        calls.push("resend");
        return HttpResponse.json(invitation());
      }),
      http.delete(`${API}/email-invitations/ei1`, () => {
        calls.push("withdraw");
        pending = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/members");
    const form = await screen.findByRole("form", { name: "Invite member" });
    await user.type(within(form).getByLabelText("Email"), "ravi@x.in");
    await user.click(within(form).getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/No account uses ravi@x.in yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Invite by email" }));
    expect(await screen.findByText(/Invitation sent to ravi@x.in/)).toBeInTheDocument();
    expect(calls[0]).toBe('invite {"email":"ravi@x.in","role":"ACCOUNTANT"}');

    const waiting = await screen.findByRole("region", { name: "Waiting to join" });
    expect(within(waiting).getByText("ravi@x.in")).toBeInTheDocument();
    await user.click(within(waiting).getByRole("button", { name: "Send again to ravi@x.in" }));
    expect(await screen.findByText("Invitation sent again to ravi@x.in.")).toBeInTheDocument();
    await user.click(
      within(waiting).getByRole("button", { name: "Withdraw the invitation to ravi@x.in" }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Waiting to join" })).not.toBeInTheDocument();
    });
    expect(calls).toEqual([calls[0], "resend", "withdraw"]);
  });
});

describe("joining from an invitation email", () => {
  it("creates the account, joins and signs in", async () => {
    let sent: unknown;
    server.use(
      http.get(`${API}/auth/join`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("token")).toBe("tok:1");
        return HttpResponse.json({
          email: "ravi@x.in",
          legal_name: "Nair Constructions",
          role: "SITE_ENGINEER",
          invited_by_name: "Asha Nair",
          expires_at: "2026-10-29T10:00:00Z",
        });
      }),
      http.post(`${API}/auth/join`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(tokens({ role: "SITE_ENGINEER" }), { status: 201 });
      }),
      http.get(`${API}/me`, () => HttpResponse.json(me({ role: "SITE_ENGINEER" }))),
      http.get(`${API}/reports/summary`, () => problem(403, "permission_denied")),
      http.get(`${API}/reports/receivables`, () => problem(403, "permission_denied")),
    );
    const user = userEvent.setup();
    const router = renderApp("/join?token=tok%3A1");
    expect(
      await screen.findByRole("heading", { name: "Join Nair Constructions" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Asha Nair invited you as site engineer.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("ravi@x.in");
    await user.type(screen.getByLabelText("Your name"), "Ravi Kumar");
    await user.type(screen.getByLabelText("Choose a password"), "three unrelated words");
    await user.click(screen.getByRole("button", { name: "Create account and join" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(sent).toEqual({
      token: "tok:1",
      full_name: "Ravi Kumar",
      password: "three unrelated words",
      client: "web",
    });
  });

  it("explains an expired invitation", async () => {
    server.use(
      http.get(`${API}/auth/join`, () =>
        fieldProblem("token", "link_expired", "This link has expired."),
      ),
    );
    renderApp("/join?token=old");
    expect(await screen.findByText(/This link has expired\. Ask the person/)).toBeInTheDocument();
  });
});
