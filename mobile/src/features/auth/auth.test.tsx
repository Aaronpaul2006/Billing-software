import { fireEvent, screen } from "@testing-library/react-native";

import {
  EMPTY_RECEIVABLES,
  EMPTY_SUMMARY,
  emptyDashboard,
  json,
  on,
  problem,
  tokens,
} from "@/test/api";
import { renderApp } from "@/test/render";
import { secureStore } from "@/test/secureStore";

const STORED = "billing.refresh_token";

async function signIn(email: string, password: string) {
  await fireEvent.changeText(await screen.findByLabelText("Email"), email);
  await fireEvent.changeText(screen.getByLabelText("Password"), password);
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
}

describe("signing in", () => {
  it("takes the password, then the 2-step code, and keeps the refresh token in secure storage", async () => {
    const sent: unknown[] = [];
    on("POST", "/auth/login", async (request) => {
      sent.push(await request.json());
      return json({ mfa_required: true, mfa_token: "mfa-1" });
    });
    on("POST", "/auth/mfa/verify", async (request) => {
      sent.push(await request.json());
      return json(tokens({ refresh_token: "refresh-1" }));
    });
    emptyDashboard();
    await renderApp("/");
    await signIn("asha@nairconstructions.in", "correct horse battery");

    expect(await screen.findByRole("header", { name: "Two-step verification" })).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Code"), "123 456");
    await fireEvent.press(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
    expect(sent).toEqual([
      { email: "asha@nairconstructions.in", password: "correct horse battery", client: "mobile" },
      { mfa_token: "mfa-1", client: "mobile", code: "123456" },
    ]);
    expect(secureStore.get(STORED)).toBe("refresh-1");
  });

  it("accepts a recovery code, and explains a wrong password", async () => {
    let attempts = 0;
    on("POST", "/auth/login", () => {
      attempts += 1;
      return attempts === 1
        ? problem(401, "invalid_credentials")
        : json({ mfa_required: true, mfa_token: "mfa-1" });
    });
    let verified: unknown;
    on("POST", "/auth/mfa/verify", async (request) => {
      verified = await request.json();
      return json(tokens());
    });
    emptyDashboard();
    await renderApp("/");
    await signIn("asha@nairconstructions.in", "wrong");
    expect(await screen.findByText("Email or password is wrong.")).toBeTruthy();

    await fireEvent.changeText(screen.getByLabelText("Password"), "correct horse battery");
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
    await fireEvent.changeText(await screen.findByLabelText("Code"), "ABCD-EFGH-1234");
    await fireEvent.press(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
    expect(verified).toEqual({
      mfa_token: "mfa-1",
      client: "mobile",
      recovery_code: "ABCD-EFGH-1234",
    });
  });

  it("sends owners without 2-step verification to the web app", async () => {
    on("POST", "/auth/login", () => json(tokens({ mfa_enrollment_required: true })));
    await renderApp("/");
    await signIn("new@owner.in", "correct horse battery");
    expect(
      await screen.findByRole("header", { name: "Turn on two-step verification" }),
    ).toBeTruthy();
  });
});

describe("the stored session", () => {
  it("is resumed on launch, and the rotated refresh token replaces it", async () => {
    let sent: unknown;
    secureStore.set(STORED, "stored-refresh");
    on("POST", "/auth/token/refresh", async (request) => {
      sent = await request.json();
      return json(tokens({ refresh_token: "refresh-2" }));
    });
    emptyDashboard();
    await renderApp("/");
    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
    expect(sent).toEqual({ refresh_token: "stored-refresh" });
    expect(secureStore.get(STORED)).toBe("refresh-2");
  });

  it("is forgotten when the server has ended it", async () => {
    secureStore.set(STORED, "revoked");
    on("POST", "/auth/token/refresh", () => problem(401, "refresh_token_reused"));
    await renderApp("/");
    expect(await screen.findByRole("header", { name: "Sign in" })).toBeTruthy();
    expect(secureStore.has(STORED)).toBe(false);
  });

  it("is kept when the server cannot be reached, and retried", async () => {
    secureStore.set(STORED, "stored-refresh");
    let online = false;
    on("POST", "/auth/token/refresh", () => {
      if (!online) throw new TypeError("Network request failed");
      return json(tokens());
    });
    emptyDashboard();
    await renderApp("/");
    expect(await screen.findByRole("header", { name: "Cannot reach the server" })).toBeTruthy();
    expect(secureStore.get(STORED)).toBe("stored-refresh");
    online = true;
    await fireEvent.press(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
  });

  it("refreshes an expired access token once for parallel requests, then retries them", async () => {
    let refreshes = 0;
    secureStore.set(STORED, "stored-refresh");
    on("POST", "/auth/token/refresh", () => {
      refreshes += 1;
      return json(tokens({ access_token: `access-${refreshes}`, refresh_token: `r-${refreshes}` }));
    });
    // The access token from launch (access-1) has expired by the time the reports load.
    const expired = (request: Request) =>
      request.headers.get("Authorization") === "Bearer access-1";
    on("GET", "/reports/summary", (request) =>
      expired(request) ? problem(401, "token_expired") : json(EMPTY_SUMMARY),
    );
    on("GET", "/reports/receivables", (request) =>
      expired(request) ? problem(401, "token_expired") : json(EMPTY_RECEIVABLES),
    );
    await renderApp("/");
    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
    expect(screen.getByText("Billed")).toBeTruthy();
    expect(refreshes).toBe(2); // launch, then one refresh shared by both reports
    expect(secureStore.get(STORED)).toBe("r-2");
  });
});
