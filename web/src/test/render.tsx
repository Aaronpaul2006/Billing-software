import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { Providers } from "@/App";
import { makeQueryClient } from "@/queryClient";
import { routes } from "@/routes";

import { API, http, HttpResponse, me, server, tokens } from "./server";
import type { Tokens } from "@/auth/session";

/** Render the whole app at `path` with a memory router. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers queryClient={makeQueryClient()}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}

/** Render signed in (the refresh cookie answers with a session). */
export function renderSignedIn(path: string, session: Partial<Tokens> = {}) {
  server.use(
    http.post(`${API}/auth/token/refresh`, () => HttpResponse.json(tokens(session))),
    http.get(`${API}/me`, () => HttpResponse.json(me())),
  );
  return renderApp(path);
}
