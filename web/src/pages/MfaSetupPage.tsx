import { useMutation } from "@tanstack/react-query";
import { AlertCircle, ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import type { ReactNode } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useAuth } from "@/auth/context";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type MfaEnabled = components["schemas"]["MfaEnabled"];

/**
 * OWNER and ADMIN must turn on two-step verification before anything else
 * works (the API answers 403 mfa_enrollment_required until then).
 */
export function MfaSetupPage() {
  const { adopt, logout } = useAuth();
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [pending, setPending] = useState<MfaEnabled | null>(null);

  const setup = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/mfa/setup")),
  });
  const enable = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/auth/mfa/enable", { body: { code: code.trim(), client: "web" } }),
      ),
    onSuccess: (result) => {
      setRecoveryCodes(result.recovery_codes);
      setPending(result); // adopt after the codes are saved: adopting leaves this page
    },
  });

  const error = setup.error ?? enable.error;

  if (recoveryCodes && pending) {
    return (
      <Shell
        title="Save your recovery codes"
        description="Each code works once if you lose your phone. Keep them somewhere safe."
      >
        <ul className="bg-muted grid grid-cols-2 gap-2 rounded-md p-4 font-mono text-sm">
          {recoveryCodes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <Button
          onClick={() => {
            adopt(pending);
          }}
        >
          I have saved them
        </Button>
      </Shell>
    );
  }

  return (
    <Shell
      title="Turn on two-step verification"
      description="Owners and admins sign in with a code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password...)."
    >
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>
            {error instanceof ApiError && error.code === "invalid_mfa_code"
              ? "That code did not work. Check the time on your phone and try again."
              : error.message}
          </AlertDescription>
        </Alert>
      )}
      {!setup.data ? (
        <Button
          onClick={() => {
            setup.mutate();
          }}
          disabled={setup.isPending}
        >
          <ShieldCheck aria-hidden /> Start
        </Button>
      ) : (
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            enable.mutate();
          }}
        >
          <div className="flex justify-center rounded-md bg-white p-4">
            <QRCodeSVG value={setup.data.otpauth_uri} size={180} title="Authenticator QR code" />
          </div>
          <p className="text-muted-foreground text-sm">
            Scan the code, or enter this key:{" "}
            <code className="font-mono break-all">{setup.data.secret}</code>
          </p>
          <div className="grid gap-2">
            <Label htmlFor="mfa-code">6-digit code</Label>
            <Input
              id="mfa-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
              }}
            />
          </div>
          <Button type="submit" disabled={enable.isPending || !/^\d{6}$/.test(code.trim())}>
            Turn on
          </Button>
        </form>
      )}
      <Button variant="ghost" onClick={() => void logout()}>
        Sign out
      </Button>
    </Shell>
  );
}

function Shell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="bg-muted flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{title}</h1>
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">{children}</CardContent>
      </Card>
    </main>
  );
}
