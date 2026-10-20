/**
 * The signed-in session, kept in memory only.
 *
 * The access token lives in this module (never localStorage: an XSS bug
 * could read it there). The refresh token is an HttpOnly cookie the API sets
 * for web clients; JavaScript never sees it.
 *
 * Refreshes are serialised: the API treats two refreshes with the same token
 * as theft and revokes the session. Inside one tab a shared promise does it;
 * across tabs a Web Lock does (each tab then sends the cookie as it is after
 * the previous tab's rotation).
 */

import type { components } from "@/api/schema";

export type Tokens = components["schemas"]["Tokens"];

type Listener = (session: Tokens | null) => void;

let current: Tokens | null = null;
let inFlight: Promise<Tokens | null> | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<Listener>();

export function getSession(): Tokens | null {
  return current;
}

export function getAccessToken(): string | null {
  return current?.access_token ?? null;
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setSession(session: Tokens | null): void {
  current = session;
  clearTimeout(timer);
  if (session) {
    // Refresh a minute before the access token expires.
    const delay = Math.max(session.expires_in - 60, 5) * 1000;
    timer = setTimeout(() => void refreshSession(), delay);
  }
  for (const listener of listeners) listener(session);
}

async function postRefresh(): Promise<Tokens | null> {
  const response = await fetch(`${window.location.origin}/api/v1/auth/token/refresh`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: "{}",
  });
  if (!response.ok) return null;
  return (await response.json()) as Tokens;
}

async function withTabLock<T>(run: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && "locks" in navigator) {
    return navigator.locks.request("billing-auth-refresh", run);
  }
  return run();
}

/**
 * Rotate the refresh cookie for a new access token. Resolves to the new
 * session, or null when the server says the session is over. A network
 * failure keeps the current session (the next request tries again).
 */
export function refreshSession(): Promise<Tokens | null> {
  inFlight ??= withTabLock(postRefresh)
    .then(
      (session) => {
        setSession(session);
        return session;
      },
      () => current,
    )
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/** For tests. */
export function resetSessionForTests(): void {
  clearTimeout(timer);
  current = null;
  inFlight = null;
  listeners.clear();
}
