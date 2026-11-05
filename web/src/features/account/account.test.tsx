import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderApp, renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, me, server, tokens } from "@/test/server";

import { describeDevice } from "./devices";

type Session = components["schemas"]["Session"];

const CHROME_WINDOWS =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36";
const SAFARI_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

function session(over: Partial<Session> = {}): Session {
  return {
    id: "s1",
    tenant_id: "t1",
    device_label: null,
    ip: "203.0.113.7",
    user_agent: SAFARI_IPHONE,
    started_at: "2026-10-20T09:00:00Z",
    last_refreshed_at: "2026-10-22T09:00:00Z",
    current: true,
    ...over,
  };
}

function devices(rows: Session[]) {
  server.use(http.get(`${API}/auth/sessions`, () => HttpResponse.json({ results: rows })));
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

describe("your account", () => {
  it("is in the user menu", async () => {
    devices([session()]);
    const user = userEvent.setup();
    const router = renderSignedIn("/");
    server.use(http.get(`${API}/reports/summary`, () => HttpResponse.json({}, { status: 403 })));
    await user.click(await screen.findByRole("button", { name: /^Asha Nair/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Your account" }));
    expect(await screen.findByRole("heading", { name: "Your account" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/account");
  });

  it("edits the profile", async () => {
    devices([session()]);
    let sent: unknown;
    server.use(
      http.patch(`${API}/me`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(me({ full_name: "Asha N.", phone: "+919847012345" }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    const form = await screen.findByRole("form", { name: "Profile" });
    const name = within(form).getByLabelText("Your name");
    await user.clear(name);
    await user.type(name, "Asha N.");
    await user.type(within(form).getByLabelText("Mobile number"), "+91 98470 12345");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByText("Saved.")).toBeInTheDocument();
    expect(sent).toEqual({ full_name: "Asha N.", phone: "+91 98470 12345" });
  });

  it("changes the email only after the new address confirms", async () => {
    devices([session()]);
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/me/email`, async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? fieldProblem("password", "invalid_password", "The password is incorrect.")
          : new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    const form = await screen.findByRole("form", { name: "Change email" });
    await user.type(within(form).getByLabelText("New email"), "asha.new@nair.in");
    await user.type(within(form).getByLabelText("Your password"), "wrong one");
    await user.click(within(form).getByRole("button", { name: "Change email" }));
    expect(await within(form).findByText("The password is incorrect.")).toBeInTheDocument();
    await user.clear(within(form).getByLabelText("Your password"));
    await user.type(within(form).getByLabelText("Your password"), "correct horse battery");
    await user.click(within(form).getByRole("button", { name: "Change email" }));
    expect(await screen.findByText(/We sent a link to asha.new@nair.in/)).toBeInTheDocument();
    expect(bodies[1]).toEqual({ new_email: "asha.new@nair.in", password: "correct horse battery" });
  });

  it("changes the password", async () => {
    devices([session()]);
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/auth/password/change`, async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? fieldProblem("new_password", "weak_password", "This password is too common.")
          : new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    const form = await screen.findByRole("form", { name: "Change password" });
    await user.type(within(form).getByLabelText("Current password"), "correct horse battery");
    await user.type(within(form).getByLabelText("New password"), "password1234");
    await user.type(within(form).getByLabelText("Repeat the new password"), "password12345");
    await user.click(within(form).getByRole("button", { name: "Change password" }));
    expect(await within(form).findByText("The two passwords do not match.")).toBeInTheDocument();
    expect(bodies).toHaveLength(0);

    await user.clear(within(form).getByLabelText("Repeat the new password"));
    await user.type(within(form).getByLabelText("Repeat the new password"), "password1234");
    await user.click(within(form).getByRole("button", { name: "Change password" }));
    expect(await within(form).findByText("This password is too common.")).toBeInTheDocument();

    const fresh = "three unrelated words";
    for (const label of ["New password", "Repeat the new password"]) {
      await user.clear(within(form).getByLabelText(label));
      await user.type(within(form).getByLabelText(label), fresh);
    }
    await user.click(within(form).getByRole("button", { name: "Change password" }));
    expect(
      await within(form).findByText("Password changed. Your other devices were signed out."),
    ).toBeInTheDocument();
    expect(bodies[1]).toEqual({ current_password: "correct horse battery", new_password: fresh });
  });

  it("owners and admins keep two-step on", async () => {
    devices([session()]);
    renderSignedIn("/account");
    expect(await screen.findByText(/Owners and admins must keep it on/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: /Turn off/ })).not.toBeInTheDocument();
  });

  it("others may turn two-step off", async () => {
    let on = true;
    let sent: unknown;
    devices([session()]);
    const user = userEvent.setup();
    renderSignedIn("/account", { role: "ACCOUNTANT" }, { role: "ACCOUNTANT" });
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(me({ role: "ACCOUNTANT", mfa_enabled: on }))),
      http.post(`${API}/auth/mfa/disable`, async ({ request }) => {
        sent = await request.json();
        on = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const form = await screen.findByRole("form", { name: "Turn off two-step verification" });
    await user.type(within(form).getByLabelText("Your password"), "correct horse battery");
    await user.type(within(form).getByLabelText("6-digit code"), "123456");
    await user.click(within(form).getByRole("button", { name: "Turn off" }));
    expect(await screen.findByText(/Off\. Turn it on/)).toBeInTheDocument();
    expect(sent).toEqual({ password: "correct horse battery", code: "123456" });
  });

  it("turns two-step on from here and shows the recovery codes once", async () => {
    devices([session()]);
    let on = false;
    const user = userEvent.setup();
    renderSignedIn("/account", { role: "ACCOUNTANT" }, { role: "ACCOUNTANT", mfa_enabled: false });
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(me({ role: "ACCOUNTANT", mfa_enabled: on }))),
      http.post(`${API}/auth/mfa/setup`, () =>
        HttpResponse.json({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x?secret=J" }),
      ),
      http.post(`${API}/auth/mfa/enable`, () => {
        on = true;
        return HttpResponse.json({
          ...tokens({ role: "ACCOUNTANT", access_token: "access-2" }),
          recovery_codes: ["abcde-12345", "fghij-67890"],
        });
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    await user.type(screen.getByLabelText("6-digit code"), "654321");
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    const codes = await screen.findByRole("list", { name: "Recovery codes" });
    expect(within(codes).getByText("abcde-12345")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "I have saved them" }));
    expect(await screen.findByText(/^On\./)).toBeInTheDocument();
  });

  it("lists the devices and signs one out", async () => {
    let rows = [
      session(),
      session({ id: "s2", current: false, user_agent: CHROME_WINDOWS, ip: "198.51.100.4" }),
    ];
    const deleted: string[] = [];
    server.use(
      http.get(`${API}/auth/sessions`, () => HttpResponse.json({ results: rows })),
      http.delete(`${API}/auth/sessions/:id`, ({ params }) => {
        deleted.push(String(params.id));
        rows = rows.filter((r) => r.id !== params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    expect(await screen.findByText("Safari on iPhone")).toBeInTheDocument();
    expect(screen.getByText("This device")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out Chrome on Windows" }));
    await waitFor(() => {
      expect(screen.queryByText("Chrome on Windows")).not.toBeInTheDocument();
    });
    expect(deleted).toEqual(["s2"]);
  });
});

describe("confirm a new email", () => {
  it("switches the address from the emailed link", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API}/auth/email/confirm`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp("/confirm-email?token=tok%3A1");
    expect(await screen.findByRole("heading", { name: "Email changed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(sent).toEqual({ token: "tok:1" });
  });

  it("explains an address taken in the meantime", async () => {
    server.use(
      http.post(`${API}/auth/email/confirm`, () =>
        fieldProblem("token", "email_taken", "An account with this email already exists."),
      ),
    );
    renderApp("/confirm-email?token=abc");
    expect(
      await screen.findByText("An account with this email already exists."),
    ).toBeInTheDocument();
  });
});

describe("describeDevice", () => {
  it("names browsers and systems, and prefers the device's own label", () => {
    expect(describeDevice(CHROME_WINDOWS, null)).toBe("Chrome on Windows");
    expect(describeDevice(SAFARI_IPHONE, null)).toBe("Safari on iPhone");
    expect(
      describeDevice("Mozilla/5.0 (Linux; Android 15) AppleWebKit Chrome/141.0 Mobile", null),
    ).toBe("Chrome on Android");
    expect(describeDevice("okhttp/4.12.0", null)).toBe("App");
    expect(describeDevice(CHROME_WINDOWS, "Asha's Pixel")).toBe("Asha's Pixel");
    expect(describeDevice(null, null)).toBe("Unknown device");
  });
});
