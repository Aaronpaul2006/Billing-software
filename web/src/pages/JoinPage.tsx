import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useAuth } from "@/auth/context";
import { FullPageSpinner } from "@/components/FullPageSpinner";
import { Field, TextField } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage, linkError } from "@/lib/errors";
import { applyServerErrors } from "@/lib/forms";

import { AuthCard } from "./AuthCard";

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter your name."),
  password: z.string().min(10, "Use at least 10 characters."),
});
type Values = z.infer<typeof schema>;

function roleName(role: string): string {
  return role.replace("_", " ").toLowerCase();
}

/** Opened from an invitation email: create the account and join the company. */
export function JoinPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { state, adopt, logout } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const details = useQuery({
    queryKey: ["join", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/auth/join", { params: { query: { token } } })),
    enabled: token !== "",
    retry: false,
    staleTime: Infinity,
  });
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", password: "" },
  });

  if (token && details.isPending) return <FullPageSpinner />;
  if (!token || details.error || !details.data) {
    const reason = !token
      ? "This link is incomplete."
      : (linkError(details.error) ?? errorMessage(details.error));
    return (
      <AuthCard title="Join a company">
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>
            {reason} Ask the person who invited you to send the invitation again.
          </AlertDescription>
        </Alert>
        <p className="text-sm">
          <Link to="/login" className="underline">
            Sign in
          </Link>
        </p>
      </AuthCard>
    );
  }

  const invitation = details.data;
  const title = `Join ${invitation.legal_name}`;
  const description = `${invitation.invited_by_name} invited you as ${roleName(invitation.role)}.`;
  if (state.status === "signed_in") {
    return (
      <AuthCard title={title} description={description}>
        <p className="text-sm">
          You are signed in. To create the invited account for {invitation.email}, sign out first.
        </p>
        <Button
          variant="outline"
          onClick={() => {
            void logout();
          }}
        >
          Sign out
        </Button>
      </AuthCard>
    );
  }

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      const session = unwrap(
        await api.POST("/api/v1/auth/join", {
          body: { token, full_name: v.full_name.trim(), password: v.password, client: "web" },
        }),
      );
      adopt(session);
      void navigate("/", { replace: true });
    } catch (e) {
      if (e instanceof ApiError && e.code === "account_exists") {
        setError("You already have an account: sign in, and accept the invitation there.");
        return;
      }
      setError(linkError(e) ?? applyServerErrors(e, form.setError, ["full_name", "password"]));
    }
  });

  return (
    <AuthCard title={title} description={description}>
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
        <Field id="join-email" label="Email">
          <Input id="join-email" value={invitation.email} readOnly />
        </Field>
        <TextField
          id="full_name"
          label="Your name"
          autoComplete="name"
          autoFocus
          error={form.formState.errors.full_name?.message}
          registration={form.register("full_name")}
        />
        <TextField
          id="password"
          label="Choose a password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters. A few unrelated words work well."
          error={form.formState.errors.password?.message}
          registration={form.register("password")}
        />
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Create account and join
        </Button>
      </form>
      <p className="text-muted-foreground text-sm">
        Already have an account?{" "}
        <Link to="/login" className="text-foreground underline">
          Sign in
        </Link>
      </p>
    </AuthCard>
  );
}
