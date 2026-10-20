import { createContext, useContext } from "react";

import type { Tokens } from "./session";

export type AuthState =
  { status: "loading" } | { status: "signed_out" } | { status: "signed_in"; session: Tokens };

export type LoginOutcome = { kind: "signed_in" } | { kind: "mfa"; mfaToken: string };

export interface SignupInput {
  full_name: string;
  business_name: string;
  email: string;
  password: string;
}

export interface AuthApi {
  state: AuthState;
  login: (email: string, password: string) => Promise<LoginOutcome>;
  /** Create an account and its first company, then sign in. */
  signup: (input: SignupInput) => Promise<void>;
  verifyMfa: (mfaToken: string, code: { code?: string; recovery_code?: string }) => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  logout: () => Promise<void>;
  /** After MFA enrolment the API issues new tokens. */
  adopt: (session: Tokens) => void;
}

export const AuthContext = createContext<AuthApi | null>(null);

export function useAuth(): AuthApi {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside AuthProvider");
  return auth;
}

/** The signed-in session; only for components rendered behind RequireAuth. */
export function useSession(): Tokens {
  const { state } = useAuth();
  if (state.status !== "signed_in") throw new Error("useSession while signed out");
  return state.session;
}
