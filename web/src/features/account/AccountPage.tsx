import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { api, unwrap } from "@/api/client";
import { useMe } from "@/api/me";
import type { components } from "@/api/schema";
import { TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ResendVerificationButton } from "@/layout/VerifyEmailBanner";
import { applyServerErrors, blankToNull } from "@/lib/forms";

import { DevicesCard, TwoStepCard } from "./SecurityCards";

type Me = components["schemas"]["Me"];
type Notice = { ok: boolean; text: string } | null;

function NoticeAlert({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return (
    <Alert variant={notice.ok ? "default" : "destructive"}>
      {notice.ok ? <CheckCircle2 aria-hidden /> : <AlertCircle aria-hidden />}
      <AlertDescription>{notice.text}</AlertDescription>
    </Alert>
  );
}

const profileSchema = z.object({
  full_name: z.string().trim().min(1, "Enter your name."),
  phone: z.string(),
});

function ProfileCard({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<Notice>(null);
  const form = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: { full_name: me.full_name, phone: me.phone ?? "" },
  });
  const save = useMutation({
    mutationFn: async (v: z.infer<typeof profileSchema>) =>
      unwrap(
        await api.PATCH("/api/v1/me", {
          body: { full_name: v.full_name.trim(), phone: blankToNull(v.phone) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["me"], saved);
      setNotice({ ok: true, text: "Saved." });
    },
    onError: (e) => {
      const text = applyServerErrors(e, form.setError, ["full_name", "phone"]);
      setNotice(text ? { ok: false, text } : null);
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Profile</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          aria-label="Profile"
          className="grid max-w-sm gap-4"
          noValidate
          onSubmit={(e) => {
            setNotice(null);
            void form.handleSubmit((v) => {
              save.mutate(v);
            })(e);
          }}
        >
          <NoticeAlert notice={notice} />
          <TextField
            id="full_name"
            label="Your name"
            autoComplete="name"
            error={form.formState.errors.full_name?.message}
            registration={form.register("full_name")}
          />
          <TextField
            id="phone"
            label="Mobile number"
            type="tel"
            autoComplete="tel"
            error={form.formState.errors.phone?.message}
            registration={form.register("phone")}
          />
          <div>
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

const emailSchema = z.object({
  new_email: z.string().trim().pipe(z.email("Enter the new email address.")),
  password: z.string().min(1, "Enter your password."),
});

function EmailCard({ me }: { me: Me }) {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const form = useForm<z.infer<typeof emailSchema>>({
    resolver: zodResolver(emailSchema),
    defaultValues: { new_email: "", password: "" },
  });
  const change = useMutation({
    mutationFn: async (v: z.infer<typeof emailSchema>) => {
      unwrap(await api.POST("/api/v1/me/email", { body: v }));
      return v.new_email;
    },
    onSuccess: (newEmail) => {
      setSentTo(newEmail);
      form.reset();
    },
    onError: (e) => {
      const text = applyServerErrors(e, form.setError, ["new_email", "password"]);
      setNotice(text ? { ok: false, text } : null);
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Sign-in email</h2>
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <span className="text-foreground">{me.email}</span>
          {me.email_verified ? (
            <Badge variant="secondary">Confirmed</Badge>
          ) : (
            <>
              <Badge variant="outline">Not confirmed</Badge>
              <ResendVerificationButton />
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {sentTo && (
          <Alert>
            <MailCheck aria-hidden />
            <AlertDescription>
              We sent a link to {sentTo}. Your sign-in email changes when you open it (within 24
              hours); until then you keep using {me.email}.
            </AlertDescription>
          </Alert>
        )}
        <form
          aria-label="Change email"
          className="grid max-w-sm gap-4"
          noValidate
          onSubmit={(e) => {
            setNotice(null);
            setSentTo(null);
            void form.handleSubmit((v) => {
              change.mutate(v);
            })(e);
          }}
        >
          <NoticeAlert notice={notice} />
          <TextField
            id="new_email"
            label="New email"
            type="email"
            autoComplete="email"
            error={form.formState.errors.new_email?.message}
            registration={form.register("new_email")}
          />
          <TextField
            id="email-password"
            label="Your password"
            type="password"
            autoComplete="current-password"
            error={form.formState.errors.password?.message}
            registration={form.register("password")}
          />
          <div>
            <Button type="submit" variant="outline" disabled={change.isPending}>
              Change email
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password."),
    new_password: z.string().min(10, "Use at least 10 characters."),
    repeat: z.string(),
  })
  .refine((v) => v.new_password === v.repeat, {
    path: ["repeat"],
    message: "The two passwords do not match.",
  });

function PasswordCard() {
  const [notice, setNotice] = useState<Notice>(null);
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", repeat: "" },
  });
  const change = useMutation({
    mutationFn: async (v: z.infer<typeof passwordSchema>) => {
      unwrap(
        await api.POST("/api/v1/auth/password/change", {
          body: { current_password: v.current_password, new_password: v.new_password },
        }),
      );
    },
    onSuccess: () => {
      form.reset();
      setNotice({ ok: true, text: "Password changed. Your other devices were signed out." });
    },
    onError: (e) => {
      const text = applyServerErrors(e, form.setError, ["current_password", "new_password"]);
      setNotice(text ? { ok: false, text } : null);
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Password</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          aria-label="Change password"
          className="grid max-w-sm gap-4"
          noValidate
          onSubmit={(e) => {
            setNotice(null);
            void form.handleSubmit((v) => {
              change.mutate(v);
            })(e);
          }}
        >
          <NoticeAlert notice={notice} />
          <TextField
            id="current_password"
            label="Current password"
            type="password"
            autoComplete="current-password"
            error={form.formState.errors.current_password?.message}
            registration={form.register("current_password")}
          />
          <TextField
            id="new_password"
            label="New password"
            type="password"
            autoComplete="new-password"
            hint="At least 10 characters. A few unrelated words work well."
            error={form.formState.errors.new_password?.message}
            registration={form.register("new_password")}
          />
          <TextField
            id="repeat_password"
            label="Repeat the new password"
            type="password"
            autoComplete="new-password"
            error={form.formState.errors.repeat?.message}
            registration={form.register("repeat")}
          />
          <div>
            <Button type="submit" variant="outline" disabled={change.isPending}>
              Change password
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function AccountPage() {
  const me = useMe();
  return (
    <>
      <PageHeader title="Your account" description="Your sign-in details and devices." />
      <div className="grid max-w-3xl gap-6">
        {!me.data ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <ProfileCard key={`profile-${me.data.id}`} me={me.data} />
            <EmailCard me={me.data} />
          </>
        )}
        <PasswordCard />
        <TwoStepCard />
        <DevicesCard />
      </div>
    </>
  );
}
