import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, MailPlus, UserX } from "lucide-react";
import { useState } from "react";

import { useConfirm } from "@/components/confirm-context";
import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { ErrorState } from "@/components/ErrorState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/errors";

function inviteMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "already_member":
        return "This person is a member of your business. Use a different email for the portal.";
      case "other_client":
        return "This person already uses the portal for another client.";
      case "already_invited":
        return "This email already has portal access or an invitation.";
    }
  }
  return errorMessage(error);
}

const STATUS: Record<string, string> = {
  ACTIVE: "Active",
  INVITED: "Invited (to accept)",
  PENDING: "Email sent",
};

/**
 * Who at this client may sign in to the client portal (W.5): their bills,
 * payments, statement and BOQ progress, and answering quotations. OWNER / ADMIN.
 */
export function PortalAccess({ partyId, partyName }: { partyId: string; partyName: string }) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const key = ["portal-users", partyId];
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const path = { party_id: partyId };

  const users = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/parties/{party_id}/portal-users", { params: { path } })),
  });

  const invite = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/parties/{party_id}/portal-users", {
          params: { path },
          body: { email: email.trim() },
        }),
      ),
    onSuccess: () => {
      setEmail("");
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (e) => {
      setNotice(inviteMessage(e));
    },
  });

  const revoke = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/parties/{party_id}/portal-users/{portal_user_id}", {
          params: { path: { party_id: partyId, portal_user_id: id } },
        }),
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
    onError: (e) => {
      setNotice(errorMessage(e));
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Client portal</CardTitle>
        <CardDescription>
          People at {partyName} who can sign in to see their bills, payments, statement and project
          progress, and accept or decline quotations. They sign in with a password and a code we
          email each time.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {notice && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
        {users.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : users.isError ? (
          <ErrorState error={users.error} />
        ) : users.data.results.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nobody has portal access yet.</p>
        ) : (
          <ul className="grid gap-2" aria-label="Portal users">
            {users.data.results.map((u) => (
              <li key={u.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="grid">
                  <span className="text-sm font-medium">{u.full_name ?? u.email}</span>
                  {u.full_name && <span className="text-muted-foreground text-xs">{u.email}</span>}
                </span>
                <span className="flex items-center gap-2">
                  <Badge variant={u.status === "ACTIVE" ? "default" : "secondary"}>
                    {STATUS[u.status] ?? u.status}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove ${u.email}`}
                    disabled={revoke.isPending}
                    onClick={() => {
                      void confirm({
                        title: `Remove portal access for ${u.email}?`,
                        description: "They can no longer sign in to see this client's bills.",
                        confirmLabel: "Remove access",
                        tone: "danger",
                      }).then((yes) => {
                        if (yes) revoke.mutate(u.id);
                      });
                    }}
                  >
                    <UserX aria-hidden />
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <form
          aria-label="Invite to the client portal"
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (email.trim()) invite.mutate();
          }}
        >
          <div className="grid min-w-60 flex-1 gap-2">
            <Label htmlFor="portal-email">Email</Label>
            <Input
              id="portal-email"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
            />
          </div>
          <Button type="submit" disabled={invite.isPending || !email.trim()}>
            <MailPlus aria-hidden /> Invite
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
