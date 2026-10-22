import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

import { AuthContext } from "./context";
import type { AuthState, LoginOutcome } from "./context";
import { getSession, refreshSession, setSession, subscribe } from "./session";
import type { RefreshResult, Tokens } from "./session";

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

  // A new session arrives through subscribe(); here only the other outcomes.
  const settle = useCallback((result: RefreshResult) => {
    if (result === "offline") setState({ status: "offline" });
    else if (!result) setState({ status: "signed_out" });
  }, []);

  useEffect(() => {
    const unsubscribe = subscribe((session) => {
      setState(session ? { status: "signed_in", session } : { status: "signed_out" });
    });
    // On launch: the stored refresh token (if any) gives a fresh access token.
    if (!getSession()) void refreshSession().then(settle);
    return unsubscribe;
  }, [settle]);

  const adopt = useCallback(
    async (session: Tokens) => {
      queryClient.clear(); // another user or company: drop every cached answer
      await setSession(session);
    },
    [queryClient],
  );

  const login = useCallback(
    async (email: string, password: string): Promise<LoginOutcome> => {
      const result = unwrap(
        await api.POST("/api/v1/auth/login", { body: { email, password, client: "mobile" } }),
      );
      if (isChallenge(result)) return { kind: "mfa", mfaToken: result.mfa_token };
      await adopt(result);
      return { kind: "signed_in" };
    },
    [adopt],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: { code?: string; recovery_code?: string }) => {
      await adopt(
        unwrap(
          await api.POST("/api/v1/auth/mfa/verify", {
            body: { mfa_token: mfaToken, client: "mobile", ...code },
          }),
        ),
      );
    },
    [adopt],
  );

  const switchTenant = useCallback(
    async (tenantId: string) => {
      await adopt(
        unwrap(
          await api.POST("/api/v1/auth/switch-tenant", {
            body: { tenant_id: tenantId, client: "mobile" },
          }),
        ),
      );
    },
    [adopt],
  );

  const logout = useCallback(async () => {
    try {
      if (getSession()) await api.POST("/api/v1/auth/logout", { body: {} });
    } catch {
      // offline: the session ends here anyway; the server's copy expires
    } finally {
      queryClient.clear();
      await setSession(null);
    }
  }, [queryClient]);

  const retry = useCallback(async () => {
    settle(await refreshSession());
  }, [settle]);

  const value = useMemo(
    () => ({ state, login, verifyMfa, switchTenant, logout, retry }),
    [state, login, verifyMfa, switchTenant, logout, retry],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
