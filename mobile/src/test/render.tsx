import { renderRouter } from "expo-router/testing-library";

import { json, on, tokens } from "./api";
import { secureStore } from "./secureStore";

type Tokens = ReturnType<typeof tokens>;

/** The whole app (src/app routes and layouts) at `url`. */
export function renderApp(url = "/") {
  return renderRouter("src/app", { initialUrl: url });
}

/**
 * Launch the app as someone signed in before: a refresh token is in secure
 * storage and the API exchanges it for `session`.
 */
export function renderSignedIn(url = "/", session: Partial<Tokens> = {}) {
  secureStore.set("billing.refresh_token", "stored-refresh");
  on("POST", "/auth/token/refresh", () => json(tokens({ refresh_token: "refresh-2", ...session })));
  return renderApp(url);
}
