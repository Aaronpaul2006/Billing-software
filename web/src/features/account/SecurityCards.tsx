import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useMe } from "@/api/me";
import { useAuth, useSession } from "@/auth/context";
import { mfaErrorText, useMfaEnrolment } from "@/auth/mfaEnrolment";
import { MfaQrForm, RecoveryCodes } from "@/auth/MfaQrForm";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/dates";

import { describeDevice } from "./devices";

function TurnOn() {
  const { adopt } = useAuth();
  const enrolment = useMfaEnrolment();
  if (enrolment.enabled) {
    const done = enrolment.enabled;
    return (
      <div className="grid gap-3">
        <p className="text-sm">
          Two-step verification is on. Save these recovery codes: each works once if you lose your
          phone.
        </p>
        <RecoveryCodes codes={done.recovery_codes} />
        <div>
          <Button
            onClick={() => {
              adopt(done); // new tokens with the second factor; other devices were signed out
            }}
          >
            I have saved them
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      {enrolment.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{mfaErrorText(enrolment.error)}</AlertDescription>
        </Alert>
      )}
      <MfaQrForm enrolment={enrolment} />
    </div>
  );
}

function TurnOff() {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const off = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/v1/auth/mfa/disable", { body: { password, code: code.trim() } }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
  return (
    <form
      aria-label="Turn off two-step verification"
      className="grid max-w-sm gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        off.mutate();
      }}
    >
      {off.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>
            {off.error instanceof ApiError && off.error.problem.errors?.length
              ? off.error.problem.errors.map((x) => x.message).join(" ")
              : errorMessage(off.error)}
          </AlertDescription>
        </Alert>
      )}
      <Field id="mfa-off-password" label="Your password">
        <Input
          id="mfa-off-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
        />
      </Field>
      <Field id="mfa-off-code" label="6-digit code">
        <Input
          id="mfa-off-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
          }}
        />
      </Field>
      <div>
        <Button
          type="submit"
          variant="outline"
          disabled={off.isPending || !password || !/^\d{6}$/.test(code.trim())}
        >
          Turn off
        </Button>
      </div>
    </form>
  );
}

/** New recovery codes (Part B): the old ones stop working; shown once. */
function NewRecoveryCodes() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const make = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/auth/mfa/recovery-codes", {
          body: { password, code: code.trim() },
        }),
      ).recovery_codes,
    onSuccess: () => {
      setPassword("");
      setCode("");
    },
  });
  if (make.data) {
    return (
      <div className="grid gap-3">
        <p className="text-sm">
          Your new recovery codes. Save them now: they are shown only once, and the old ones no
          longer work.
        </p>
        <RecoveryCodes codes={make.data} />
        <div>
          <Button
            variant="outline"
            onClick={() => {
              make.reset();
              setOpen(false);
            }}
          >
            I have saved them
          </Button>
        </div>
      </div>
    );
  }
  if (!open) {
    return (
      <div className="grid gap-1">
        <div>
          <Button
            variant="outline"
            onClick={() => {
              setOpen(true);
            }}
          >
            Make new recovery codes
          </Button>
        </div>
        <p className="text-help text-muted-foreground">
          If you used some, lost them or think someone saw them. The old ones stop working.
        </p>
      </div>
    );
  }
  return (
    <form
      aria-label="Make new recovery codes"
      className="grid max-w-sm gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        make.mutate();
      }}
    >
      {make.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>
            {make.error instanceof ApiError && make.error.problem.errors?.length
              ? make.error.problem.errors.map((x) => x.message).join(" ")
              : errorMessage(make.error)}
          </AlertDescription>
        </Alert>
      )}
      <Field id="codes-password" label="Your password">
        <Input
          id="codes-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
        />
      </Field>
      <Field id="codes-code" label="6-digit code from your app">
        <Input
          id="codes-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
          }}
        />
      </Field>
      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={make.isPending || !password || !/^\d{6}$/.test(code.trim())}
        >
          Make new codes
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setOpen(false);
            make.reset();
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function TwoStepCard() {
  const me = useMe();
  const session = useSession();
  const required = session.role === "OWNER" || session.role === "ADMIN";
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Two-step verification</h2>
        </CardTitle>
        <CardDescription>
          A code from an authenticator app on your phone, besides your password.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {!me.data ? (
          <Skeleton className="h-10 w-full" />
        ) : me.data.mfa_enabled ? (
          <>
            <p className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="text-success size-4" aria-hidden /> On.
              {required && " Owners and admins must keep it on."}
            </p>
            <NewRecoveryCodes />
            {!required && <TurnOff />}
          </>
        ) : (
          <>
            <p className="text-sm">Off. Turn it on to protect your account.</p>
            <TurnOn />
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function DevicesCard() {
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/sessions")).results,
  });
  const signOut = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/auth/sessions/{session_id}", {
          params: { path: { session_id: id } },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const rows = [...(sessions.data ?? [])].sort((a, b) => Number(b.current) - Number(a.current));
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Your devices</h2>
        </CardTitle>
        <CardDescription>
          Where you are signed in. Sign out anything you do not know.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {sessions.error ? (
          <ErrorState error={sessions.error} />
        ) : !sessions.data ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <ul className="grid">
            {rows.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-center gap-3 border-b py-3 text-sm last:border-b-0"
              >
                <div className="grid min-w-48 flex-1 gap-0.5">
                  <span className="font-medium">
                    {describeDevice(s.user_agent, s.device_label)}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {s.ip ? `${s.ip} · ` : ""}signed in {formatDateTime(s.started_at)} · last active{" "}
                    {formatDateTime(s.last_refreshed_at)}
                  </span>
                </div>
                {s.current ? (
                  <Badge variant="secondary">This device</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={signOut.isPending}
                    aria-label={`Sign out ${describeDevice(s.user_agent, s.device_label)}`}
                    onClick={() => {
                      signOut.mutate(s.id);
                    }}
                  >
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
