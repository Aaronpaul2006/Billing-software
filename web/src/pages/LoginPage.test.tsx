import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderApp as renderAt } from "@/test/render";
import { API, http, HttpResponse, me, problem, server, tokens } from "@/test/server";

describe("sign in", () => {
  it("sends a signed-out visitor to the login page", async () => {
    renderAt("/documents");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("password, then the MFA code, then back to the page asked for", async () => {
    const user = userEvent.setup();
    let loginBody: unknown;
    server.use(
      http.post(`${API}/auth/login`, async ({ request }) => {
        loginBody = await request.json();
        return HttpResponse.json({ mfa_required: true, mfa_token: "mfa-1" });
      }),
      http.post(`${API}/auth/mfa/verify`, async ({ request }) => {
        const body = (await request.json()) as { code?: string; client?: string };
        return body.code === "123456" && body.client === "web"
          ? HttpResponse.json(tokens())
          : problem(401, "invalid_mfa_code");
      }),
      http.get(`${API}/me`, () => HttpResponse.json(me())),
    );
    const router = renderAt("/documents");
    await user.type(await screen.findByLabelText("Email"), "asha@nairconstructions.in");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(loginBody).toEqual({
      email: "asha@nairconstructions.in",
      password: "correct horse battery",
      client: "web",
    });

    await user.type(await screen.findByLabelText("Code"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/That code did not work/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Code"));
    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Invoices & quotes" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/documents");
    expect(await screen.findAllByText("Nair Constructions")).not.toHaveLength(0);
  });

  it("shows one message for a wrong email or password", async () => {
    const user = userEvent.setup();
    server.use(http.post(`${API}/auth/login`, () => problem(401, "invalid_credentials")));
    renderAt("/login");
    await user.type(await screen.findByLabelText("Email"), "x@example.com");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Email or password is wrong.")).toBeInTheDocument();
  });

  it("validates before calling the API", async () => {
    const user = userEvent.setup();
    renderAt("/login");
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
  });

  it("a returning visitor with a refresh cookie goes straight in", async () => {
    server.use(
      http.post(`${API}/auth/token/refresh`, () => HttpResponse.json(tokens())),
      http.get(`${API}/me`, () => HttpResponse.json(me())),
    );
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("owners without MFA must enrol before anything else", async () => {
    server.use(
      http.post(`${API}/auth/token/refresh`, () =>
        HttpResponse.json(tokens({ mfa_enrollment_required: true })),
      ),
    );
    renderAt("/payments");
    expect(
      await screen.findByRole("heading", { name: "Turn on two-step verification" }),
    ).toBeInTheDocument();
  });
});
