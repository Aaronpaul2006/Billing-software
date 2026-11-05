import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Mail } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useSession } from "@/auth/context";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";
import { compareMoney, formatInr } from "@/lib/money";
import { formatDateTime } from "@/lib/dates";
import { can } from "@/lib/permissions";

const STAGES: Record<string, string> = {
  BEFORE_DUE: "3 days before the due date",
  ON_DUE: "On the due date",
  OVERDUE_7: "7 days overdue",
  OVERDUE_15: "15 days overdue",
  OVERDUE_30: "30 days overdue",
  MANUAL: "Sent by hand",
};

function problemText(e: unknown, partyId: string) {
  if (e instanceof ApiError && e.problem.errors?.some((x) => x.code === "no_client_email")) {
    return (
      <>
        This client has no email address.{" "}
        <Link to={`/parties/${partyId}`} className="underline">
          Add one on the client&apos;s page
        </Link>
        .
      </>
    );
  }
  return e instanceof ApiError ? e.message : errorMessage(e);
}

/** Payment reminders for an issued bill: what went out, and "send one now". */
export function DocumentReminders({
  documentId,
  partyId,
  outstanding,
}: {
  documentId: string;
  partyId: string;
  outstanding: string;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["reminders", documentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/reminders", {
          params: { path: { document_id: documentId } },
        }),
      ).results,
  });
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/reminders", {
          params: { path: { document_id: documentId } },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (sent) => {
      setKey(newIdempotencyKey());
      setSentTo(sent.sent_to);
      void queryClient.invalidateQueries({ queryKey: ["reminders", documentId] });
    },
  });
  const due = compareMoney(outstanding, "0") === 1;
  const rows = history.data ?? [];
  if (!due && rows.length === 0) return null;
  return (
    <section aria-label="Payment reminders" className="mt-6 max-w-3xl">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h2 className="font-medium">Payment reminders</h2>
        {due && can(session.role, "payments.record") && (
          <Button
            size="sm"
            variant="outline"
            disabled={send.isPending}
            onClick={() => {
              setSentTo(null);
              send.mutate();
            }}
          >
            <Mail aria-hidden /> Send reminder
          </Button>
        )}
      </div>
      <p className="text-muted-foreground mb-2 text-sm">
        Sent by email automatically 3 days before the due date, on it, and 7, 15 and 30 days after,
        while the bill is unpaid (the client&apos;s page can switch this off).
      </p>
      {sentTo && (
        <Alert className="mb-2">
          <CheckCircle2 aria-hidden />
          <AlertDescription>Reminder sent to {sentTo}.</AlertDescription>
        </Alert>
      )}
      {send.error && (
        <Alert variant="destructive" className="mb-2">
          <AlertCircle aria-hidden />
          <AlertDescription>{problemText(send.error, partyId)}</AlertDescription>
        </Alert>
      )}
      {rows.length === 0 ? (
        <p className="text-sm">None sent yet.</p>
      ) : (
        <ul className="divide-y rounded-md border text-sm">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap justify-between gap-2 px-3 py-2">
              <span>
                {STAGES[r.stage] ?? r.stage}
                {r.sent_by_name ? ` (${r.sent_by_name})` : ""} · to {r.sent_to}
              </span>
              <span className="text-muted-foreground">
                {formatInr(r.amount_due)} due · {formatDateTime(r.sent_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
