import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MailOpen } from "lucide-react";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";

/** Invitations to other companies, for the signed-in user: accept or decline. */
export function InvitationsBanner() {
  const queryClient = useQueryClient();
  const invitations = useQuery({
    queryKey: ["invitations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/invitations")).results,
    staleTime: 5 * 60_000,
  });
  const respond = useMutation({
    mutationFn: async ({ id, accept }: { id: string; accept: boolean }) => {
      const path = { membership_id: id };
      if (accept) {
        unwrap(await api.POST("/api/v1/invitations/{membership_id}/accept", { params: { path } }));
      } else {
        unwrap(await api.POST("/api/v1/invitations/{membership_id}/decline", { params: { path } }));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
      void queryClient.invalidateQueries({ queryKey: ["me"] }); // the company switcher lists it now
    },
  });
  if (!invitations.data?.length) return null;
  return (
    <div className="grid gap-2 border-b bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
      {invitations.data.map((inv) => (
        <div key={inv.id} role="status" className="flex flex-wrap items-center gap-3">
          <MailOpen className="size-4" aria-hidden />
          <span>
            {inv.invited_by_name ?? "Someone"} invited you to <strong>{inv.legal_name}</strong> as{" "}
            {inv.role.toLowerCase().replace("_", " ")}.
          </span>
          <Button
            size="sm"
            disabled={respond.isPending}
            onClick={() => {
              respond.mutate({ id: inv.id, accept: true });
            }}
          >
            Accept
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={respond.isPending}
            onClick={() => {
              respond.mutate({ id: inv.id, accept: false });
            }}
          >
            Decline
          </Button>
        </div>
      ))}
    </div>
  );
}
