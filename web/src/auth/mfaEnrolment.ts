import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";

export type MfaEnabled = components["schemas"]["MfaEnabled"];

/**
 * Turning on two-step verification: a secret to scan, a code to prove it, then
 * the one-time recovery codes. The new tokens (`enabled`) are adopted only once
 * the codes are saved, because adopting them can leave the page.
 */
export function useMfaEnrolment() {
  const [code, setCode] = useState("");
  const [enabled, setEnabled] = useState<MfaEnabled | null>(null);
  const setup = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/mfa/setup")),
  });
  const enable = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/auth/mfa/enable", { body: { code: code.trim(), client: "web" } }),
      ),
    onSuccess: setEnabled,
  });
  return { code, setCode, setup, enable, enabled, error: setup.error ?? enable.error };
}

export type MfaEnrolment = ReturnType<typeof useMfaEnrolment>;

export function mfaErrorText(error: Error): string {
  return error instanceof ApiError && error.code === "invalid_mfa_code"
    ? "That code did not work. Check the time on your phone and try again."
    : error.message;
}
