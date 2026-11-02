import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

import { getSession, refreshSession, setSession, subscribe } from "./session";
import type { Tokens } from "./session";
import { AuthContext } from "./context";
import type { AuthState, LoginOutcome, SignupInput } from "./context";

type LoginResult = components["schemas"]["LoginResult"];

function isChallenge(result: LoginResult): result is components["schemas"]["MfaChallenge"] {
  return "mfa_required" in result && result.mfa_required;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>(() => {
    const session = getSession();
    return session ? { status: "signed_in", session } : { status: "loading" };
  });

  useEffect(() => {
    const unsubscribe = subscribe((session) => {
      setState(session ? { status: "signed_in", session } : { status: "signed_out" });
    });
    // On load: the refresh cookie (if any) gives a fresh access token.
    if (!getSession()) {
      void refreshSession().then((session) => {
        if (!session) setState({ status: "signed_out" });
      });
    }
    return unsubscribe;
  }, []);

  const adopt = useCallback(
    (session: Tokens) => {
      queryClient.clear(); // another user or tenant: drop every cached answer
      setSession(session);
    },
    [queryClient],
  );

  const login = useCallback(
    async (email: string, password: string): Promise<LoginOutcome> => {
      const result = unwrap(
        await api.POST("/api/v1/auth/login", { body: { email, password, client: "web" } }),
      );
      if (isChallenge(result)) {
        return { kind: "mfa", mfaToken: result.mfa_token, method: result.mfa_method };
      }
      adopt(result);
      return { kind: "signed_in" };
    },
    [adopt],
  );

  const signup = useCallback(
    async (input: SignupInput) => {
      adopt(unwrap(await api.POST("/api/v1/auth/signup", { body: { ...input, client: "web" } })));
    },
    [adopt],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: { code?: string; recovery_code?: string }) => {
      adopt(
        unwrap(
          await api.POST("/api/v1/auth/mfa/verify", {
            body: { mfa_token: mfaToken, client: "web", ...code },
          }),
        ),
      );
    },
    [adopt],
  );

  const switchTenant = useCallback(
    async (tenantId: string) => {
      adopt(
        unwrap(
          await api.POST("/api/v1/auth/switch-tenant", {
            body: { tenant_id: tenantId, client: "web" },
          }),
        ),
      );
    },
    [adopt],
  );

  const logout = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout", { body: {} });
    } finally {
      queryClient.clear();
      setSession(null);
    }
  }, [queryClient]);

  const value = useMemo(
    () => ({ state, login, signup, verifyMfa, switchTenant, logout, adopt }),
    [state, login, signup, verifyMfa, switchTenant, logout, adopt],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
