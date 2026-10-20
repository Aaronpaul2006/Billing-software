import { useMutation, useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";

import { api, unwrap } from "@/api/client";
import { meQuery } from "@/api/me";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

export function ResendVerificationButton() {
  const resend = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/v1/auth/verify-email/resend"));
    },
  });
  if (resend.isSuccess)
    return <span className="text-muted-foreground">Sent. Check your inbox.</span>;
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={resend.isPending}
        onClick={() => {
          resend.mutate();
        }}
      >
        Send a new link
      </Button>
      {resend.isError && <span className="text-destructive">{errorMessage(resend.error)}</span>}
    </>
  );
}

/** Until the address is confirmed: invoices cannot be issued (403 email_not_verified). */
export function VerifyEmailBanner() {
  // The link usually opens in another tab: look again when the user comes back.
  const me = useQuery({ ...meQuery, refetchOnWindowFocus: "always" });
  if (!me.data || me.data.email_verified) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 border-b bg-sky-50 p-3 text-sm dark:bg-sky-950/30"
    >
      <Mail className="size-4" aria-hidden />
      <span>
        Confirm your email address: we sent a link to <strong>{me.data.email}</strong>. You need it
        to issue invoices.
      </span>
      <ResendVerificationButton />
    </div>
  );
}
