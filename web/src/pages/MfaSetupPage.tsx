import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";

import { useAuth } from "@/auth/context";
import { mfaErrorText, useMfaEnrolment } from "@/auth/mfaEnrolment";
import { MfaQrForm, RecoveryCodes } from "@/auth/MfaQrForm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * OWNER and ADMIN must turn on two-step verification before anything else
 * works (the API answers 403 mfa_enrollment_required until then).
 */
export function MfaSetupPage() {
  const { adopt, logout } = useAuth();
  const enrolment = useMfaEnrolment();

  if (enrolment.enabled) {
    const done = enrolment.enabled;
    return (
      <Shell
        title="Save your recovery codes"
        description="Each code works once if you lose your phone. Keep them somewhere safe."
      >
        <RecoveryCodes codes={done.recovery_codes} />
        <Button
          onClick={() => {
            adopt(done);
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
      {enrolment.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{mfaErrorText(enrolment.error)}</AlertDescription>
        </Alert>
      )}
      <MfaQrForm enrolment={enrolment} />
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
