/**
 * The signed-in session: the access token in memory, the refresh token in
 * secure storage (refreshToken.ts).
 *
 * Refreshes are serialised with one shared promise: the API treats two
 * refreshes with the same token as theft and revokes the session.
 */

import type { components } from "@/api/schema";
import { API_URL } from "@/config";

import { forgetRefreshToken, readRefreshToken, saveRefreshToken } from "./refreshToken";

export type Tokens = components["schemas"]["Tokens"];

/** "offline": the server could not be reached; the stored token is kept. */
export type RefreshResult = Tokens | null | "offline";

type Listener = (session: Tokens | null) => void;

let current: Tokens | null = null;
let inFlight: Promise<RefreshResult> | null = null;
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

/** Adopt new tokens (sign-in, refresh, company switch) or clear them (sign-out). */
export async function setSession(session: Tokens | null): Promise<void> {
  current = session;
  clearTimeout(timer);
  if (session) {
    if (session.refresh_token) await saveRefreshToken(session.refresh_token);
    // Refresh a minute before the access token expires (timers pause while the
    // app is in the background; then the first 401 token_expired refreshes).
    const delay = Math.max(session.expires_in - 60, 5) * 1000;
    timer = setTimeout(() => void refreshSession(), delay);
  } else {
    await forgetRefreshToken();
  }
  for (const listener of listeners) listener(session);
}

async function postRefresh(): Promise<RefreshResult> {
  const token = await readRefreshToken();
  if (!token) return null;
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/auth/token/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    });
  } catch {
    return "offline";
  }
  if (response.status === 401 || response.status === 403) return null; // ended or revoked
  if (!response.ok) return "offline"; // 5xx, 429: try again later with the same token
  return (await response.json()) as Tokens;
}

/**
 * Rotate the refresh token for a new access token. Resolves to the new
 * session; null when the server says the session is over (the stored token
 * is forgotten); "offline" when it could not be reached (nothing changes).
 */
export function refreshSession(): Promise<RefreshResult> {
  inFlight ??= postRefresh()
    .then(async (result) => {
      if (result !== "offline") await setSession(result);
      return result;
    })
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
