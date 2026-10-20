import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";
import { z } from "zod";

import { api, unwrap } from "@/api/client";
import { TextField } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

import { AuthCard } from "./AuthCard";

const schema = z.object({ email: z.string().trim().pipe(z.email("Enter your email address.")) });

export function ForgotPasswordPage() {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/password/forgot", { body: { email } }));
      setSentTo(email);
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <AuthCard
      title="Reset your password"
      description={sentTo ? undefined : "We will email you a link to choose a new password."}
    >
      {sentTo ? (
        <Alert>
          <MailCheck aria-hidden />
          <AlertDescription>
            If an account uses {sentTo}, a reset link is on its way. It works for one hour. Check
            your spam folder if it does not arrive in a few minutes.
          </AlertDescription>
        </Alert>
      ) : (
        <>
          {error && (
            <Alert variant="destructive">
              <AlertCircle aria-hidden />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
            <TextField
              id="email"
              label="Email"
              type="email"
              autoComplete="username"
              autoFocus
              error={form.formState.errors.email?.message}
              registration={form.register("email")}
            />
            <Button type="submit" disabled={form.formState.isSubmitting}>
              Send reset link
            </Button>
          </form>
        </>
      )}
      <p className="text-sm">
        <Link to="/login" className="underline">
          Back to sign in
        </Link>
      </p>
    </AuthCard>
  );
}
