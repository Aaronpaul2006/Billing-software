import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/context";
import { FullPageSpinner } from "@/components/FullPageSpinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ResendVerificationButton } from "@/layout/VerifyEmailBanner";
import { errorMessage, linkError } from "@/lib/errors";

import { AuthCard } from "./AuthCard";

/** Opened from the verification email, signed in or not (often on a phone). */
export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { state } = useAuth();
  const queryClient = useQueryClient();
  const signedIn = state.status === "signed_in";
  // A query, not a mutation: it runs once per link however often the page renders.
  const verify = useQuery({
    queryKey: ["verify-email", token],
    queryFn: async () => {
      unwrap(await api.POST("/api/v1/auth/verify-email", { body: { token } }));
      void queryClient.invalidateQueries({ queryKey: ["me"] });
      return true;
    },
    enabled: token !== "",
    retry: false,
    staleTime: Infinity,
  });

  if (token && verify.isPending) return <FullPageSpinner />;
  if (verify.isSuccess) {
    return (
      <AuthCard title="Email confirmed">
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>Thank you. You can now issue invoices.</AlertDescription>
        </Alert>
        <Button asChild>
          <Link to={signedIn ? "/" : "/login"}>{signedIn ? "Continue" : "Sign in"}</Link>
        </Button>
      </AuthCard>
    );
  }
  const problem = token ? (linkError(verify.error) ?? errorMessage(verify.error)) : null;
  return (
    <AuthCard title="Confirm your email">
      <Alert variant="destructive">
        <AlertCircle aria-hidden />
        <AlertDescription>{problem ?? "This link is incomplete."}</AlertDescription>
      </Alert>
      {signedIn ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <ResendVerificationButton />
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">
          <Link to="/login" className="text-foreground underline">
            Sign in
          </Link>{" "}
          to get a new link.
        </p>
      )}
    </AuthCard>
  );
}
