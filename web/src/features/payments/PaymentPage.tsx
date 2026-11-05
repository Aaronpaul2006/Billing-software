import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { ifMatch } from "@/lib/forms";
import { compareMoney, formatInr } from "@/lib/money";
import { formatDate } from "@/lib/dates";

import { allocationProblems, toAllocationItems, useOpenItems } from "./allocations";
import type { Allocations } from "./allocations";
import { AllocationTable } from "./AllocationTable";
import { MODE_LABELS } from "./modes";

type Payment = components["schemas"]["Payment"];

function paymentKey(id: string) {
  return ["payment", id] as const;
}

function message(error: unknown): string {
  if (error instanceof ApiError && error.problem.errors?.length) {
    return error.problem.errors.map((e) => e.message).join(" ");
  }
  return errorMessage(error);
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function AllocateRest({ payment }: { payment: Payment }) {
  const queryClient = useQueryClient();
  const [allocations, setAllocations] = useState<Allocations>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [error, setError] = useState<string | null>(null);
  const open = useOpenItems(payment.party_id, true);
  const problems = allocationProblems(open.data ?? [], allocations, payment.unallocated);
  const allocate = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payments/{payment_id}/allocations", {
          params: { path: { payment_id: payment.id } },
          body: { allocations: toAllocationItems(allocations) },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (updated) => {
      setKey(newIdempotencyKey());
      setAllocations({});
      queryClient.setQueryData(paymentKey(updated.id), updated);
      void queryClient.invalidateQueries({ queryKey: ["open-items"] });
      void queryClient.invalidateQueries({ queryKey: ["payments"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (e) => {
      setError(message(e));
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Allocate the rest</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <AllocationTable
          items={open.data ?? []}
          allocations={allocations}
          onChange={setAllocations}
          available={payment.unallocated}
          isLoading={open.isPending}
          error={open.error}
        />
        {[...problems, ...(error ? [error] : [])].map((p) => (
          <p key={p} className="text-destructive text-sm">
            {p}
          </p>
        ))}
        <div>
          <Button
            disabled={
              allocate.isPending ||
              problems.length > 0 ||
              toAllocationItems(allocations).length === 0
            }
            onClick={() => {
              setError(null);
              allocate.mutate();
            }}
          >
            Allocate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function PaymentPage() {
  const { paymentId = "" } = useParams();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [reason, setReason] = useState("");
  const payment = useQuery({
    queryKey: paymentKey(paymentId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/payments/{payment_id}", {
          params: { path: { payment_id: paymentId } },
        }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: paymentKey(paymentId) });
    void queryClient.invalidateQueries({ queryKey: ["open-items"] });
    void queryClient.invalidateQueries({ queryKey: ["payments"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };
  const unwind = useMutation({
    mutationFn: async (allocationId: string) => {
      unwrap(
        await api.DELETE("/api/v1/allocations/{allocation_id}", {
          params: { path: { allocation_id: allocationId } },
        }),
      );
    },
    onSuccess: refresh,
    onError: (e) => {
      setNotice(message(e));
    },
  });
  const voidPayment = useMutation({
    mutationFn: async (p: Payment) =>
      unwrap(
        await api.POST("/api/v1/payments/{payment_id}/void", {
          params: { path: { payment_id: p.id } },
          body: { reason: reason.trim() },
          headers: { "If-Match": ifMatch(p.version) },
        }),
      ),
    onSuccess: (updated) => {
      setVoiding(false);
      queryClient.setQueryData(paymentKey(updated.id), updated);
      refresh();
    },
    onError: (e) => {
      setNotice(
        e instanceof ApiError && e.code === "stale_version"
          ? "Someone else changed this payment. Reload the page."
          : message(e),
      );
    },
  });

  if (payment.error) return <ErrorState error={payment.error} />;
  if (!payment.data) return <Skeleton className="h-96 w-full" />;
  const p = payment.data;
  const recorded = p.status === "RECORDED";

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/payments">
          <ArrowLeft aria-hidden /> Payments
        </Link>
      </Button>
      <PageHeader
        title={`${formatInr(p.amount)} from ${p.party_name}`}
        description={
          recorded ? (
            `${MODE_LABELS[p.mode]} on ${formatDate(p.payment_date)}`
          ) : (
            <span className="flex items-center gap-2">
              <Badge variant="secondary">Voided</Badge>
              {p.void_reason}
            </span>
          )
        }
        actions={
          recorded && (
            <Button
              variant="ghost"
              onClick={() => {
                setVoiding(true);
              }}
            >
              Void payment…
            </Button>
          )
        }
      />
      <div className="grid gap-6">
        {notice && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
        {voiding && (
          <form
            aria-label="Void payment"
            className="bg-muted/40 grid max-w-xl gap-3 rounded-lg border p-4"
            onSubmit={(e) => {
              e.preventDefault();
              voidPayment.mutate(p);
            }}
          >
            <p className="text-sm">
              Its allocations are unwound and the payment is kept, marked voided. It cannot be
              undone.
            </p>
            <Label htmlFor="void-reason">Reason</Label>
            <Input
              id="void-reason"
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
            <div className="flex gap-2">
              <Button
                type="submit"
                variant="destructive"
                disabled={voidPayment.isPending || reason.trim().length < 3}
              >
                Void payment
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setVoiding(false);
                }}
              >
                Keep it
              </Button>
            </div>
          </form>
        )}
        <Card>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-4">
              <Info label="Client">
                <Link to={`/parties/${p.party_id}`} className="hover:underline">
                  {p.party_name}
                </Link>
              </Info>
              <Info label="Reference">{p.reference ?? "–"}</Info>
              <Info label="Allocated">{formatInr(p.allocated)}</Info>
              <Info label="Unallocated">{formatInr(p.unallocated)}</Info>
              {p.project_name && <Info label="Project">{p.project_name}</Info>}
              {p.notes && <Info label="Notes">{p.notes}</Info>}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <h2>Settled</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {p.allocations.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                Not allocated: an advance from the client.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Document</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {p.allocations.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell>
                        {a.document_id ? (
                          <Link
                            to={`/documents/${a.document_id}`}
                            className="font-medium hover:underline"
                          >
                            {a.doc_number}
                          </Link>
                        ) : (
                          "Retention release"
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInr(a.amount)}
                      </TableCell>
                      <TableCell className="text-right">
                        {recorded && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={unwind.isPending}
                            onClick={() => {
                              if (
                                window.confirm(
                                  "Unwind this allocation? The document becomes unpaid by this amount.",
                                )
                              )
                                unwind.mutate(a.id);
                            }}
                          >
                            Unwind
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {recorded && compareMoney(p.unallocated, "0") === 1 && <AllocateRest payment={p} />}
      </div>
    </>
  );
}
