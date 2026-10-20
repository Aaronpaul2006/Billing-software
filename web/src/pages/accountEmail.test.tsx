import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/problem";
import { errorMessage } from "@/lib/errors";
import { renderApp, renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server, tokens } from "@/test/server";

/** A 422 naming one field, as the API sends for a bad link or a taken email. */
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

describe("sign up", () => {
  it("explains a taken email, then creates the account and asks for two-step setup", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/auth/signup`, async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? fieldProblem("email", "email_taken", "An account with this email already exists.")
          : HttpResponse.json(tokens({ mfa_enrollment_required: true }), { status: 201 });
      }),
      http.post(`${API}/auth/mfa/setup`, () =>
        HttpResponse.json({ secret: "ABC", otpauth_uri: "otpauth://totp/x?secret=ABC" }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/login");
    await user.click(await screen.findByRole("link", { name: "Create an account" }));
    await user.type(await screen.findByLabelText("Your name"), "Asha Nair");
    await user.type(screen.getByLabelText("Business name"), "Nair Constructions");
    await user.type(screen.getByLabelText("Email"), "asha@nair.in");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(bodies).toHaveLength(0);

    await user.type(screen.getByLabelText("Password"), " and longer");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(
      await screen.findByText("An account with this email already exists."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(
      await screen.findByRole("heading", { name: "Turn on two-step verification" }),
    ).toBeInTheDocument();
    expect(bodies[1]).toEqual({
      full_name: "Asha Nair",
      business_name: "Nair Constructions",
      email: "asha@nair.in",
      password: "short and longer",
      client: "web",
    });
  });
});

describe("forgot and reset password", () => {
  it("sends a reset link without saying whether the account exists", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API}/auth/password/forgot`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/login");
    await user.click(await screen.findByRole("link", { name: "Forgot password?" }));
    await user.type(await screen.findByLabelText("Email"), "asha@nair.in");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If an account uses asha@nair.in/)).toBeInTheDocument();
    expect(sent).toEqual({ email: "asha@nair.in" });
  });

  it("sets the new password from the link", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API}/auth/password/reset`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/reset-password?token=tok%3A1");
    await user.type(await screen.findByLabelText("New password"), "a brand new passphrase");
    await user.type(screen.getByLabelText("Repeat the new password"), "a brand new passphrase!");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByText("The two passwords do not match.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Repeat the new password"));
    await user.type(screen.getByLabelText("Repeat the new password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByRole("heading", { name: "Password changed" })).toBeInTheDocument();
    expect(sent).toEqual({ token: "tok:1", password: "a brand new passphrase" });
  });

  it("offers a new link when the link has expired", async () => {
    server.use(
      http.post(`${API}/auth/password/reset`, () =>
        fieldProblem("token", "link_expired", "This link has expired. Ask for a new one."),
      ),
    );
    const user = userEvent.setup();
    renderApp("/reset-password?token=old");
    await user.type(await screen.findByLabelText("New password"), "a brand new passphrase");
    await user.type(screen.getByLabelText("Repeat the new password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByText(/This link has expired/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Send a new link" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});

describe("email verification", () => {
  it("confirms the address from the emailed link", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API}/auth/verify-email`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp("/verify-email?token=abc");
    expect(await screen.findByRole("heading", { name: "Email confirmed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(sent).toEqual({ token: "abc" });
  });

  it("explains a used link", async () => {
    server.use(
      http.post(`${API}/auth/verify-email`, () =>
        fieldProblem("token", "link_invalid", "This link is not valid."),
      ),
    );
    renderApp("/verify-email?token=used");
    expect(
      await screen.findByText("This link has already been used or is not valid."),
    ).toBeInTheDocument();
  });

  it("shows a banner until the address is confirmed, with a resend button", async () => {
    let resent = 0;
    server.use(
      http.post(`${API}/auth/verify-email/resend`, () => {
        resent += 1;
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    renderSignedIn("/parties", {}, { email_verified: false });
    expect(await screen.findByText(/Confirm your email address/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send a new link" }));
    expect(await screen.findByText("Sent. Check your inbox.")).toBeInTheDocument();
    await waitFor(() => {
      expect(resent).toBe(1);
    });
  });

  it("is not shown once confirmed", async () => {
    server.use(
      http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    renderSignedIn("/parties");
    await screen.findByRole("navigation", { name: "Main" });
    expect(screen.queryByText(/Confirm your email address/)).not.toBeInTheDocument();
  });

  it("explains why an unverified user cannot issue", () => {
    const error = new ApiError({
      type: "/errors/email_not_verified",
      title: "Forbidden",
      status: 403,
      code: "email_not_verified",
    });
    expect(errorMessage(error)).toMatch(/^Confirm your email address first/);
  });
});
