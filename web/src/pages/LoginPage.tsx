import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { z } from "zod";

import { ApiError } from "@/api/problem";
import { useAuth } from "@/auth/context";
import type { MfaMethod } from "@/auth/context";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const credentials = z.object({
  email: z.string().trim().pipe(z.email("Enter your email address.")),
  password: z.string().min(1, "Enter your password."),
});

const mfaCode = z.object({
  code: z
    .string()
    .trim()
    .regex(/^(\d{6}|[A-Za-z0-9-]{8,20})$/, "Enter the 6-digit code or a recovery code."),
});

function message(error: unknown, method: MfaMethod | null = null): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "invalid_credentials":
        return "Email or password is wrong.";
      case "invalid_mfa_code":
        return method === "email"
          ? "That code did not work. Use the latest email we sent, or sign in again for a new code."
          : "That code did not work. Check the time on your phone and try again.";
      case "invalid_mfa_token":
        return "The sign-in took too long. Start again.";
      case "no_active_membership":
        return "Your account is not active in any company.";
      default:
        return error.message;
    }
  }
  return "Could not reach the server. Check your connection and try again.";
}

export function LoginPage() {
  const { state, login, verifyMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [method, setMethod] = useState<MfaMethod>("totp");
  const [error, setError] = useState<string | null>(null);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const loginForm = useForm<z.infer<typeof credentials>>({
    resolver: zodResolver(credentials),
    defaultValues: { email: "", password: "" },
  });
  const mfaForm = useForm<z.infer<typeof mfaCode>>({
    resolver: zodResolver(mfaCode),
    defaultValues: { code: "" },
  });

  if (state.status === "signed_in") return <Navigate to={from} replace />;

  const onLogin = loginForm.handleSubmit(async ({ email, password }) => {
    setError(null);
    try {
      const outcome = await login(email, password);
      if (outcome.kind === "mfa") {
        setMethod(outcome.method);
        setMfaToken(outcome.mfaToken);
      } else void navigate(from, { replace: true });
    } catch (e) {
      setError(message(e));
    }
  });

  const onMfa = mfaForm.handleSubmit(async ({ code }) => {
    if (!mfaToken) return;
    if (method === "email" && !/^\d{6}$/.test(code)) {
      mfaForm.setError("code", { message: "Enter the 6-digit code from the email." });
      return;
    }
    setError(null);
    try {
      await verifyMfa(mfaToken, /^\d{6}$/.test(code) ? { code } : { recovery_code: code });
      void navigate(from, { replace: true });
    } catch (e) {
      if (e instanceof ApiError && e.code === "invalid_mfa_token") setMfaToken(null);
      setError(message(e, method));
    }
  });

  return (
    <main className="bg-muted flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{mfaToken ? "Two-step verification" : "Sign in"}</h1>
          </CardTitle>
          <CardDescription>
            {!mfaToken
              ? "Construction billing"
              : method === "email"
                ? "We emailed you a 6-digit code. Enter it to finish signing in (it works for 10 minutes)."
                : "Enter the 6-digit code from your authenticator app, or a recovery code."}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertCircle aria-hidden />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {mfaToken ? (
            <form onSubmit={(e) => void onMfa(e)} className="grid gap-4" noValidate>
              <div className="grid gap-2">
                <Label htmlFor="code">Code</Label>
                <Input
                  id="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  aria-invalid={!!mfaForm.formState.errors.code}
                  {...mfaForm.register("code")}
                />
                {mfaForm.formState.errors.code && (
                  <p className="text-destructive text-sm">
                    {mfaForm.formState.errors.code.message}
                  </p>
                )}
              </div>
              <Button type="submit" disabled={mfaForm.formState.isSubmitting}>
                Verify
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setMfaToken(null);
                  setError(null);
                }}
              >
                Back
              </Button>
            </form>
          ) : (
            <form onSubmit={(e) => void onLogin(e)} className="grid gap-4" noValidate>
              <div className="grid gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  aria-invalid={!!loginForm.formState.errors.email}
                  {...loginForm.register("email")}
                />
                {loginForm.formState.errors.email && (
                  <p className="text-destructive text-sm">
                    {loginForm.formState.errors.email.message}
                  </p>
                )}
              </div>
              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <Link to="/forgot-password" className="text-muted-foreground text-sm underline">
                    Forgot password?
                  </Link>
                </div>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  aria-invalid={!!loginForm.formState.errors.password}
                  {...loginForm.register("password")}
                />
                {loginForm.formState.errors.password && (
                  <p className="text-destructive text-sm">
                    {loginForm.formState.errors.password.message}
                  </p>
                )}
              </div>
              <Button type="submit" disabled={loginForm.formState.isSubmitting}>
                Sign in
              </Button>
              <p className="text-muted-foreground text-sm">
                New here?{" "}
                <Link to="/signup" className="text-foreground underline">
                  Create an account
                </Link>
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
