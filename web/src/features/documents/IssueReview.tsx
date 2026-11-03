import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Pencil } from "lucide-react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatInr } from "@/lib/money";

import { DOC_TYPE_LABELS, documentKey } from "./api";
import type { Document } from "./api";

/** Where to fix each warning. */
function fixLink(code: string, doc: Document) {
  if (code === "no_number_series") return { to: "/settings/series", text: "Add a number series" };
  if (code === "client_no_gstin")
    return { to: `/parties/${doc.party_id}`, text: "Open the client" };
  return { to: `/documents/${doc.id}/edit`, text: "Edit the bill" };
}

/**
 * The last look before issuing (B.14): what goes out, and anything worth a
 * second look. Warnings only: the bill can always be issued from here.
 */
export function IssueReview({
  doc,
  busy,
  onIssue,
  onClose,
}: {
  doc: Document;
  busy: boolean;
  onIssue: () => void;
  onClose: () => void;
}) {
  const review = useQuery({
    queryKey: [...documentKey(doc.id), "review"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/review", {
          params: { path: { document_id: doc.id } },
        }),
      ).warnings,
    staleTime: 0, // always the bill as it is now
  });
  const label = DOC_TYPE_LABELS[doc.doc_type].toLowerCase();
  const net = doc.totals.net_receivable;
  return (
    <section
      aria-label="Review before issuing"
      className="bg-muted/40 grid max-w-2xl gap-4 rounded-lg border p-4 text-sm"
    >
      <h2 className="text-base font-semibold">Review before issuing</h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
        <dt className="text-muted-foreground">Client</dt>
        <dd>{doc.party_name}</dd>
        <dt className="text-muted-foreground">Lines</dt>
        <dd>{doc.lines.length}</dd>
        <dt className="text-muted-foreground">Total</dt>
        <dd className="font-medium">₹{formatInr(doc.totals.grand_total)}</dd>
        {net !== doc.totals.grand_total && (
          <>
            <dt className="text-muted-foreground">Client pays now</dt>
            <dd>₹{formatInr(net)}</dd>
          </>
        )}
      </dl>
      {review.isPending ? (
        <Skeleton className="h-12 w-full" />
      ) : review.error ? (
        <p className="text-muted-foreground">
          The bill could not be checked just now; you can still issue it.
        </p>
      ) : review.data.length === 0 ? (
        <p className="flex items-center gap-2 text-green-700 dark:text-green-400">
          <CheckCircle2 className="size-4" aria-hidden /> Everything looks right.
        </p>
      ) : (
        <div className="grid gap-2">
          <p className="font-medium">
            {review.data.length === 1 ? "One thing" : `${String(review.data.length)} things`} to
            check (you can still issue):
          </p>
          <ul aria-label="Warnings" className="grid gap-2">
            {review.data.map((w, i) => {
              const fix = fixLink(w.code, doc);
              return (
                <li
                  key={`${w.code}-${String(i)}`}
                  className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 dark:border-amber-700 dark:bg-amber-950/40"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
                  <span>
                    {w.message}{" "}
                    <Link to={fix.to} className="underline">
                      {fix.text}
                    </Link>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <p className="text-muted-foreground">
        Issuing gives the {label} the next number. After that it cannot be edited, only corrected
        with a credit or debit note.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button autoFocus disabled={busy} onClick={onIssue}>
          Issue now
        </Button>
        <Button variant="outline" asChild>
          <Link to={`/documents/${doc.id}/edit`}>
            <Pencil aria-hidden /> Go back and edit
          </Link>
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </section>
  );
}
