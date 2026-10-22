import { createContext, useContext } from "react";

import type { Tokens } from "./session";

export type AuthState =
  | { status: "loading" }
  | { status: "offline" } // signed in before, but the server cannot be reached
  | { status: "signed_out" }
  | { status: "signed_in"; session: Tokens };

export type LoginOutcome = { kind: "signed_in" } | { kind: "mfa"; mfaToken: string };

export interface AuthApi {
  state: AuthState;
  login: (email: string, password: string) => Promise<LoginOutcome>;
  verifyMfa: (mfaToken: string, code: { code?: string; recovery_code?: string }) => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Try the stored session again (after "offline"). */
  retry: () => Promise<void>;
}

export const AuthContext = createContext<AuthApi | null>(null);

export function useAuth(): AuthApi {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside AuthProvider");
  return auth;
}

/** The signed-in session; only for screens behind the signed-in guard. */
export function useSession(): Tokens {
  const { state } = useAuth();
  if (state.status !== "signed_in") throw new Error("useSession while signed out");
  return state.session;
}
