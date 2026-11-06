import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Field } from "@/components/FormField";
import { Money } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { isoDate } from "@/features/dashboard/periods";
import { formatDate } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { cleanMoneyInput, compareMoney, MONEY_INPUT } from "@/lib/money";

import { workOrderKey } from "./api";
import type { RetentionRelease, WorkOrderDetail } from "./api";

function message(e: unknown): string {
  return e instanceof ApiError && e.problem.errors?.length
    ? e.problem.errors.map((x) => x.message).join(" ")
    : e instanceof Error
      ? e.message
      : "Something went wrong.";
}

function ReleaseForm({ wo, onDone }: { wo: WorkOrderDetail; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [amount, setAmount] = useState(wo.retention_to_release);
  const [date, setDate] = useState(isoDate(new Date()));
  const [due, setDue] = useState("");
  const [reference, setReference] = useState("");
  const clean = cleanMoneyInput(amount);
  const ok =
    MONEY_INPUT.test(clean) &&
    compareMoney(clean, "0") === 1 &&
    compareMoney(clean, wo.retention_to_release) !== 1;
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/work-orders/{wo_id}/retention-releases", {
          params: { path: { wo_id: wo.id } },
          body: {
            release_date: date,
            due_date: due || null,
            amount: clean,
            reference: reference.trim() || null,
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workOrderKey(wo.id) });
      void queryClient.invalidateQueries({ queryKey: ["work-orders"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-retention-releases"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      onDone();
    },
  });
  return (
    <form
      aria-label="Release retention"
      className="mt-4 grid gap-3 rounded-md border p-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.error && (
        <Alert variant="destructive" className="sm:col-span-2">
          <AlertCircle aria-hidden />
          <AlertDescription>{message(save.error)}</AlertDescription>
        </Alert>
      )}
      <Field
        id="release-amount"
        label="Amount to release (₹)"
        hint={`At most ${wo.retention_to_release}`}
      >
        <Input
          id="release-amount"
          inputMode="decimal"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
        />
      </Field>
      <Field id="release-ref" label="Reference (optional)">
        <Input
          id="release-ref"
          placeholder="e.g. defects period over"
          value={reference}
          onChange={(e) => {
            setReference(e.target.value);
          }}
        />
      </Field>
      <Field id="release-date" label="Released on">
        <Input
          id="release-date"
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
          }}
        />
      </Field>
      <Field id="release-due" label="Pay by (optional)">
        <Input
          id="release-due"
          type="date"
          value={due}
          onChange={(e) => {
            setDue(e.target.value);
          }}
        />
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={!ok || save.isPending}>
          Release
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Not now
        </Button>
      </div>
    </form>
  );
}

function ReleaseRow({
  r,
  wo,
  mayRecord,
}: {
  r: RetentionRelease;
  wo: WorkOrderDetail;
  mayRecord: boolean;
}) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/vendor-retention-releases/{release_id}/cancel", {
          params: { path: { release_id: r.id } },
          body: { reason: "Released by mistake" },
          headers: { "If-Match": ifMatch(r.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workOrderKey(wo.id) });
      void queryClient.invalidateQueries({ queryKey: ["vendor-retention-releases"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
    },
  });
  const paid = compareMoney(r.amount_paid, "0") === 1;
  return (
    <li className="flex flex-wrap items-center gap-3 py-2 text-sm">
      <span className="min-w-40 flex-1">
        <Money value={r.amount} /> released {formatDate(r.release_date)}
        {r.reference && <span className="text-muted-foreground"> · {r.reference}</span>}
        {r.due_date && (
          <span className="text-muted-foreground"> · pay by {formatDate(r.due_date)}</span>
        )}
      </span>
      {r.status === "CANCELLED" ? (
        <StatusBadge status="cancelled" />
      ) : compareMoney(r.outstanding, "0") === 0 ? (
        <StatusBadge status="paid" />
      ) : paid ? (
        <StatusBadge status="part_paid" />
      ) : (
        <StatusBadge status="issued">To pay</StatusBadge>
      )}
      {mayRecord && r.status === "RELEASED" && !paid && (
        <Button
          variant="ghost"
          size="sm"
          disabled={cancel.isPending}
          aria-label={`Cancel the release of ${r.amount}`}
          onClick={() => {
            cancel.mutate();
          }}
        >
          Cancel
        </Button>
      )}
      {cancel.error && (
        <span className="text-destructive w-full text-xs">{message(cancel.error)}</span>
      )}
    </li>
  );
}

/** Retention held on the work order's RA bills, and what is released to be paid. */
export function RetentionPanel({ wo, mayRecord }: { wo: WorkOrderDetail; mayRecord: boolean }) {
  const [releasing, setReleasing] = useState(false);
  const canRelease = mayRecord && compareMoney(wo.retention_to_release, "0") === 1;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>
          <h2>Retention</h2>
        </CardTitle>
        <CardDescription>
          Held <Money value={wo.retention_held} /> · released{" "}
          <Money value={wo.retention_released} /> · still held{" "}
          <Money value={wo.retention_to_release} strong />
        </CardDescription>
      </CardHeader>
      <CardContent>
        {wo.releases.length > 0 && (
          <ul aria-label="Retention released" className="divide-border divide-y">
            {wo.releases.map((r) => (
              <ReleaseRow key={r.id} r={r} wo={wo} mayRecord={mayRecord} />
            ))}
          </ul>
        )}
        {canRelease && !releasing && (
          <Button
            variant="outline"
            className="mt-2"
            onClick={() => {
              setReleasing(true);
            }}
          >
            Release retention…
          </Button>
        )}
        {releasing && (
          <ReleaseForm
            wo={wo}
            onDone={() => {
              setReleasing(false);
            }}
          />
        )}
        {!canRelease && wo.releases.length === 0 && (
          <p className="text-muted-foreground text-sm">
            Retention is held back on each RA bill; release it when it is due (after the defects
            period, say), and pay it like a bill.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
