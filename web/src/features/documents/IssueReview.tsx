import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Pencil } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { Field } from "@/components/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { MODE_LABELS } from "@/features/payments/modes";
import { cleanMoneyInput, formatInr, MONEY_INPUT, toPaise } from "@/lib/money";
import { can } from "@/lib/permissions";

import { DOC_TYPE_LABELS, documentKey } from "./api";
import type { Document } from "./api";

export type PaidNow = components["schemas"]["PaidNow"];
type Mode = components["schemas"]["PaymentModeEnum"];

/** Bills that can be paid as they are issued (Part B: "Paid now"). */
const PAYABLE_NOW: ReadonlySet<string> = new Set(["TAX_INVOICE", "BILL_OF_SUPPLY"]);

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
  onIssue: (paid?: PaidNow) => void;
  onClose: () => void;
}) {
  const { role } = useSession();
  const payable = PAYABLE_NOW.has(doc.doc_type) && can(role, "payments.record");
  const [paidNow, setPaidNow] = useState(false);
  const [amount, setAmount] = useState(doc.totals.net_receivable);
  const [mode, setMode] = useState<Mode>("CASH");
  const [reference, setReference] = useState("");
  const clean = cleanMoneyInput(amount);
  const amountOk = MONEY_INPUT.test(clean) && (toPaise(clean) ?? 0n) > 0n;
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
        <dd className="font-medium">{formatInr(doc.totals.grand_total)}</dd>
        {net !== doc.totals.grand_total && (
          <>
            <dt className="text-muted-foreground">Client pays now</dt>
            <dd>{formatInr(net)}</dd>
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
        <p className="text-success flex items-center gap-2">
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
                  className="border-warning-border bg-warning-soft flex gap-2 rounded-md border p-2"
                >
                  <AlertTriangle className="text-warning mt-0.5 size-4 shrink-0" aria-hidden />
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
      {payable && (
        <fieldset className="grid gap-3 rounded-md border p-3">
          <legend className="sr-only">Paid now</legend>
          <label className="flex min-h-6 items-center gap-2 font-medium">
            <input
              type="checkbox"
              checked={paidNow}
              onChange={(e) => {
                setPaidNow(e.target.checked);
              }}
            />
            Paid now, with the bill
          </label>
          <p className="text-muted-foreground -mt-2">
            Cash or UPI received at the counter: recorded and set against this bill as it is issued.
          </p>
          {paidNow && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field
                id="paid-amount"
                label="Amount received (₹)"
                error={amountOk ? undefined : "Enter the amount received."}
              >
                <Input
                  id="paid-amount"
                  inputMode="decimal"
                  value={amount}
                  aria-invalid={!amountOk}
                  onChange={(e) => {
                    setAmount(e.target.value);
                  }}
                />
              </Field>
              <Field id="paid-mode" label="How">
                <NativeSelect
                  id="paid-mode"
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as Mode);
                  }}
                >
                  {Object.entries(MODE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field id="paid-reference" label="Reference (optional)">
                <Input
                  id="paid-reference"
                  placeholder="UTR, cheque number"
                  value={reference}
                  onChange={(e) => {
                    setReference(e.target.value);
                  }}
                />
              </Field>
            </div>
          )}
        </fieldset>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          autoFocus
          disabled={busy || (paidNow && !amountOk)}
          onClick={() => {
            onIssue(
              paidNow ? { amount: clean, mode, reference: reference.trim() || null } : undefined,
            );
          }}
        >
          {paidNow ? "Issue and record the payment" : "Issue now"}
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
