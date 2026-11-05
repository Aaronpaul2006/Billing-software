import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, MailPlus } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/dates";

type Role = components["schemas"]["RoleEnum"];

const ROLE_LABELS: Record<Role, { label: string; can: string }> = {
  OWNER: { label: "Owner", can: "everything, including other owners" },
  ADMIN: { label: "Admin", can: "everything except owners" },
  ACCOUNTANT: { label: "Accountant", can: "billing, payments, reports" },
  SITE_ENGINEER: { label: "Site engineer", can: "drafts, BOQ, expenses" },
  VIEWER: { label: "Viewer", can: "read only, reports" },
};

function problemText(e: unknown): string {
  if (e instanceof ApiError) {
    // The API reports a missing account on the email field (422 validation_error).
    const codes = [e.code, ...(e.problem.errors ?? []).map((x) => x.code)];
    switch (codes.find((c) => c === "no_account" || c === "last_owner") ?? e.code) {
      case "no_account":
        return "There is no account with this email yet.";
      case "last_owner":
        return "The company must keep at least one owner.";
      default:
        if (e.problem.errors?.length) return e.problem.errors.map((x) => x.message).join(" ");
    }
  }
  return errorMessage(e);
}

function isNoAccount(e: unknown): boolean {
  return e instanceof ApiError && (e.problem.errors ?? []).some((x) => x.code === "no_account");
}

function WaitingToJoin({ notify }: { notify: (n: Notice) => void }) {
  const queryClient = useQueryClient();
  const pending = useQuery({
    queryKey: ["email-invitations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/email-invitations")).results,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["email-invitations"] });
  };
  const resend = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/email-invitations/{invitation_id}/resend", {
          params: { path: { invitation_id: id } },
        }),
      ),
    onSuccess: (sent) => {
      notify({ ok: true, text: `Invitation sent again to ${sent.email}.` });
      refresh();
    },
    onError: (e) => {
      notify({ ok: false, text: problemText(e) });
    },
  });
  const withdraw = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/email-invitations/{invitation_id}", {
          params: { path: { invitation_id: id } },
        }),
      );
    },
    onSuccess: refresh,
    onError: (e) => {
      notify({ ok: false, text: problemText(e) });
    },
  });
  if (!pending.data?.length) return null;
  return (
    <section aria-label="Waiting to join" className="mt-8 max-w-3xl">
      <h2 className="mb-2 font-medium">Waiting to join</h2>
      <p className="text-muted-foreground mb-2 text-sm">
        Invited by email: they join when they create their account from the link (7 days).
      </p>
      <Table>
        <TableBody>
          {pending.data.map((x) => (
            <TableRow key={x.id}>
              <TableCell>
                {x.email}
                <div className="text-muted-foreground text-xs">sent {formatDate(x.created_at)}</div>
              </TableCell>
              <TableCell>
                {ROLE_LABELS[x.role as Role].label}
                {x.expired && (
                  <Badge variant="secondary" className="ml-2">
                    Link expired
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={resend.isPending}
                  aria-label={`Send again to ${x.email}`}
                  onClick={() => {
                    resend.mutate(x.id);
                  }}
                >
                  Send again
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={withdraw.isPending}
                  aria-label={`Withdraw the invitation to ${x.email}`}
                  onClick={() => {
                    withdraw.mutate(x.id);
                  }}
                >
                  Withdraw
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

type Notice = { ok: boolean; text: string } | null;

export function MembersPage() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("ACCOUNTANT");
  const [notice, setNotice] = useState<Notice>(null);
  const [noAccount, setNoAccount] = useState<{ email: string; role: Role } | null>(null);
  const members = useQuery({
    queryKey: ["members"],
    queryFn: async () => unwrap(await api.GET("/api/v1/members")).results,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["members"] });
  };
  const onError = (e: Error) => {
    setNotice({ ok: false, text: problemText(e) });
  };
  const invite = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/members", { body: { email: email.trim(), role } })),
    onSuccess: () => {
      setEmail("");
      setNotice(null);
      refresh();
    },
    onError: (e) => {
      if (isNoAccount(e)) {
        setNoAccount({ email: email.trim(), role });
        return;
      }
      onError(e);
    },
  });
  const inviteByEmail = useMutation({
    mutationFn: async (target: { email: string; role: Role }) =>
      unwrap(await api.POST("/api/v1/email-invitations", { body: target })),
    onSuccess: (sent) => {
      setNoAccount(null);
      setEmail("");
      setNotice({
        ok: true,
        text: `Invitation sent to ${sent.email}. They join when they create their account from the link.`,
      });
      void queryClient.invalidateQueries({ queryKey: ["email-invitations"] });
    },
    onError,
  });
  const changeRole = useMutation({
    mutationFn: async ({ id, next }: { id: string; next: Role }) =>
      unwrap(
        await api.PATCH("/api/v1/members/{membership_id}", {
          params: { path: { membership_id: id } },
          body: { role: next },
        }),
      ),
    onSuccess: refresh,
    onError,
  });
  const revoke = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/members/{membership_id}", {
          params: { path: { membership_id: id } },
        }),
      );
    },
    onSuccess: refresh,
    onError,
  });
  const roles = (Object.keys(ROLE_LABELS) as Role[]).filter(
    (r) => r !== "OWNER" || session.role === "OWNER", // admins cannot make owners
  );

  return (
    <>
      <PageHeader
        title="Members"
        description="People who can sign in to this company, and what they may do."
      />
      <form
        aria-label="Invite member"
        className="bg-muted/40 mb-6 grid max-w-3xl gap-4 rounded-lg border p-4 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          setNotice(null);
          setNoAccount(null);
          invite.mutate();
        }}
      >
        <Field
          id="invite-email"
          label="Email"
          hint="People without an account yet can be invited by email."
        >
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
          />
        </Field>
        <Field id="invite-role" label="Role" hint={ROLE_LABELS[role].can}>
          <NativeSelect
            id="invite-role"
            value={role}
            onChange={(e) => {
              setRole(e.target.value as Role);
            }}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r].label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="flex items-start pt-6">
          <Button type="submit" disabled={invite.isPending || !email.includes("@")}>
            Invite
          </Button>
        </div>
      </form>
      {noAccount && (
        <Alert className="mb-4 max-w-3xl">
          <MailPlus aria-hidden />
          <AlertDescription className="grid gap-2">
            <span>
              No account uses {noAccount.email} yet. Send an invitation by email: they create their
              account from the link and join as {ROLE_LABELS[noAccount.role].label.toLowerCase()}.
            </span>
            <span>
              <Button
                size="sm"
                disabled={inviteByEmail.isPending}
                onClick={() => {
                  inviteByEmail.mutate(noAccount);
                }}
              >
                Invite by email
              </Button>
            </span>
          </AlertDescription>
        </Alert>
      )}
      {notice && (
        <Alert variant={notice.ok ? "default" : "destructive"} className="mb-4 max-w-3xl">
          {notice.ok ? <CheckCircle2 aria-hidden /> : <AlertCircle aria-hidden />}
          <AlertDescription>{notice.text}</AlertDescription>
        </Alert>
      )}
      {members.error ? (
        <ErrorState error={members.error} />
      ) : !members.data ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.data.map((m) => {
              const self = m.user_id === session.user_id;
              const protectedOwner = m.role === "OWNER" && session.role !== "OWNER";
              return (
                <TableRow key={m.id}>
                  <TableCell>
                    {m.full_name}
                    {self && <span className="text-muted-foreground"> (you)</span>}
                    <div className="text-muted-foreground text-xs">{m.email}</div>
                  </TableCell>
                  <TableCell>
                    {self || protectedOwner ? (
                      ROLE_LABELS[m.role as Role].label
                    ) : (
                      <NativeSelect
                        aria-label={`Role of ${m.full_name}`}
                        className="w-auto"
                        value={m.role}
                        disabled={changeRole.isPending}
                        onChange={(e) => {
                          changeRole.mutate({ id: m.id, next: e.target.value as Role });
                        }}
                      >
                        {roles.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r].label}
                          </option>
                        ))}
                      </NativeSelect>
                    )}
                    {m.status === "INVITED" && (
                      <Badge variant="outline" className="ml-2">
                        Invited
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {!self && !protectedOwner && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={revoke.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${m.full_name} from the company? They are signed out at once.`,
                            )
                          )
                            revoke.mutate(m.id);
                        }}
                      >
                        {m.status === "INVITED" ? "Withdraw invitation" : "Remove"}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      <WaitingToJoin notify={setNotice} />
    </>
  );
}
