import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, ShieldCheck } from "lucide-react";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { compareMoney, formatInr } from "@/lib/money";

import { documentKey } from "./api";
import type { Document } from "./api";

const COVERED = new Set(["TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE", "CREDIT_NOTE"]);

/**
 * Bill approval (Part B): a draft at or above the business's approval limit
 * waits for an owner's approval before anyone else issues it.
 */
export function ApprovalPanel({ doc }: { doc: Document }) {
  const { role } = useSession();
  const queryClient = useQueryClient();
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant")),
    staleTime: 60_000,
  });
  const run = useMutation({
    mutationFn: async (action: "ask" | "approve") => {
      const opts = {
        params: { path: { document_id: doc.id } },
        headers: { "If-Match": ifMatch(doc.version) },
      };
      return unwrap(
        action === "ask"
          ? await api.POST("/api/v1/documents/{document_id}/approval-request", opts)
          : await api.POST("/api/v1/documents/{document_id}/approve", opts),
      );
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(documentKey(saved.id), saved);
    },
  });

  const limit = tenant.data?.approval_limit ?? null;
  if (doc.status !== "DRAFT" || limit === null || !COVERED.has(doc.doc_type)) return null;
  if (compareMoney(doc.totals.grand_total, limit) === -1) return null;
  const owner = role === "OWNER";
  const error = run.error && (
    <p className="text-destructive mt-2 text-sm">
      <AlertCircle className="mr-1 inline size-4" aria-hidden />
      {run.error.message}
    </p>
  );

  if (doc.approval_holds) {
    return (
      <Alert>
        <CheckCircle2 aria-hidden />
        <AlertTitle>Approved</AlertTitle>
        <AlertDescription>
          {doc.approved_by_name} approved this draft
          {doc.approved_at ? ` on ${formatDateTime(doc.approved_at)}` : ""}. Any change to it needs
          a new approval.
        </AlertDescription>
      </Alert>
    );
  }
  if (owner) {
    // owners need no approval to issue; they approve others' drafts
    if (!doc.approval_requested_at) return null;
    return (
      <Alert>
        <ShieldCheck aria-hidden />
        <AlertTitle>Approval asked</AlertTitle>
        <AlertDescription>
          <p>
            Asked on {formatDateTime(doc.approval_requested_at)}: bills of {formatInr(limit)} or
            more wait for an owner before they are issued.
          </p>
          <Button
            className="mt-2"
            disabled={run.isPending}
            onClick={() => {
              run.mutate("approve");
            }}
          >
            Approve this draft
          </Button>
          {error}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert>
      <ShieldCheck aria-hidden />
      <AlertTitle>Needs an owner&apos;s approval</AlertTitle>
      <AlertDescription>
        <p>
          Bills of {formatInr(limit)} or more are approved by an owner before they are issued.
          {doc.approval_requested_at &&
            ` Asked on ${formatDateTime(doc.approval_requested_at)}; the owners have been told.`}
        </p>
        <Button
          variant={doc.approval_requested_at ? "outline" : "default"}
          className="mt-2"
          disabled={run.isPending}
          onClick={() => {
            run.mutate("ask");
          }}
        >
          {doc.approval_requested_at ? "Ask again" : "Ask for approval"}
        </Button>
        {error}
      </AlertDescription>
    </Alert>
  );
}
