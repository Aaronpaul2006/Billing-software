import { fireEvent, screen } from "@testing-library/react-native";

import { emptyDashboard, json, me, on, TENANT_B, tokens } from "@/test/api";
import { renderSignedIn } from "@/test/render";
import { secureStore } from "@/test/secureStore";

describe("account", () => {
  it("switches company and comes back to that company's dashboard", async () => {
    let switched: unknown;
    emptyDashboard();
    on("GET", "/me", () => json(me()));
    on("POST", "/auth/switch-tenant", async (request) => {
      switched = await request.json();
      return json(tokens({ tenant_id: TENANT_B, role: "ACCOUNTANT", refresh_token: "refresh-b" }));
    });
    await renderSignedIn("/account");
    expect(await screen.findByText("asha@nairconstructions.in")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Nair Constructions, current company" }),
    ).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Switch to Nair Infra" }));
    expect(await screen.findByText("Nothing outstanding.")).toBeTruthy();
    expect(switched).toEqual({ tenant_id: TENANT_B, client: "mobile" });
    expect(secureStore.get("billing.refresh_token")).toBe("refresh-b");
  });

  it("signs out: the server ends the session and the phone forgets it", async () => {
    let loggedOut = false;
    on("GET", "/me", () => json(me()));
    on("POST", "/auth/logout", () => {
      loggedOut = true;
      return new Response(null, { status: 204 });
    });
    await renderSignedIn("/account");
    await fireEvent.press(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("header", { name: "Sign in" })).toBeTruthy();
    expect(loggedOut).toBe(true);
    expect(secureStore.has("billing.refresh_token")).toBe(false);
  });
});
