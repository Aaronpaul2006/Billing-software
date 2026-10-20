import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router";
import { z } from "zod";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/context";
import { TextField } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { linkError } from "@/lib/errors";
import { applyServerErrors } from "@/lib/forms";

import { AuthCard } from "./AuthCard";

const schema = z
  .object({
    password: z.string().min(10, "Use at least 10 characters."),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    path: ["confirm"],
    message: "The two passwords do not match.",
  });
type Values = z.infer<typeof schema>;

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { state, logout } = useAuth();
  const [done, setDone] = useState(false);
  const [badLink, setBadLink] = useState<string | null>(token ? null : "This link is incomplete.");
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirm: "" },
  });
  const errors = form.formState.errors;

  const onSubmit = form.handleSubmit(async ({ password }) => {
    setError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/password/reset", { body: { token, password } }));
      setDone(true);
      // Every session was signed out, this tab's too.
      if (state.status === "signed_in") void logout();
    } catch (e) {
      const problem = linkError(e);
      if (problem) setBadLink(problem);
      else setError(applyServerErrors(e, form.setError, ["password"]));
    }
  });

  if (done) {
    return (
      <AuthCard title="Password changed">
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>
            Your new password is set, and you have been signed out on every device.
          </AlertDescription>
        </Alert>
        <Button asChild>
          <Link to="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }
  if (badLink) {
    return (
      <AuthCard title="Reset your password">
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{badLink} Ask for a new link below.</AlertDescription>
        </Alert>
        <Button asChild>
          <Link to="/forgot-password">Send a new link</Link>
        </Button>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Choose a new password" description="This signs you out on every device.">
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
        <TextField
          id="password"
          label="New password"
          type="password"
          autoComplete="new-password"
          autoFocus
          hint="At least 10 characters. A few unrelated words work well."
          error={errors.password?.message}
          registration={form.register("password")}
        />
        <TextField
          id="confirm"
          label="Repeat the new password"
          type="password"
          autoComplete="new-password"
          error={errors.confirm?.message}
          registration={form.register("confirm")}
        />
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Set new password
        </Button>
      </form>
    </AuthCard>
  );
}
