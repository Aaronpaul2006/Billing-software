import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useAuth } from "@/auth/context";
import { FullPageSpinner } from "@/components/FullPageSpinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage, linkError } from "@/lib/errors";

import { AuthCard } from "./AuthCard";

function problemText(error: unknown): string {
  const link = linkError(error);
  if (link) return `${link} Ask for the change again from your account.`;
  if (error instanceof ApiError && error.problem.errors?.length) {
    return error.problem.errors.map((e) => e.message).join(" ");
  }
  return errorMessage(error);
}

/** Opened from the "confirm your new email address" email, signed in or not. */
export function ConfirmEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { state } = useAuth();
  const queryClient = useQueryClient();
  const signedIn = state.status === "signed_in";
  // A query, not a mutation: it runs once per link however often the page renders.
  const confirm = useQuery({
    queryKey: ["confirm-email", token],
    queryFn: async () => {
      unwrap(await api.POST("/api/v1/auth/email/confirm", { body: { token } }));
      void queryClient.invalidateQueries({ queryKey: ["me"] });
      return true;
    },
    enabled: token !== "",
    retry: false,
    staleTime: Infinity,
  });

  const back = signedIn ? (
    <Button asChild>
      <Link to="/account">Your account</Link>
    </Button>
  ) : (
    <Button asChild>
      <Link to="/login">Sign in</Link>
    </Button>
  );
  if (token && confirm.isPending) return <FullPageSpinner />;
  if (confirm.isSuccess) {
    return (
      <AuthCard title="Email changed">
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>
            Your sign-in email is changed. Use the new address from now on.
          </AlertDescription>
        </Alert>
        {back}
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Change your email">
      <Alert variant="destructive">
        <AlertCircle aria-hidden />
        <AlertDescription>
          {token ? problemText(confirm.error) : "This link is incomplete."}
        </AlertDescription>
      </Alert>
      {back}
    </AuthCard>
  );
}
