import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { MODE_LABELS } from "@/features/payments/modes";
import { formatDate } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { can } from "@/lib/permissions";

export function VendorPaymentPage() {
  const { paymentId = "" } = useParams();
  const { role } = useSession();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [voiding, setVoiding] = useState(false);
  const payment = useQuery({
    queryKey: ["vendor-payment", paymentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/vendor-payments/{payment_id}", {
          params: { path: { payment_id: paymentId } },
        }),
      ),
  });
  const voidIt = useMutation({
    mutationFn: async (version: number) =>
      unwrap(
        await api.POST("/api/v1/vendor-payments/{payment_id}/void", {
          params: { path: { payment_id: paymentId } },
          body: { reason: reason.trim() },
          headers: { "If-Match": ifMatch(version) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["vendor-payment", paymentId], saved);
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-payments"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      setVoiding(false);
    },
  });
  if (payment.error) return <ErrorState error={payment.error} />;
  if (!payment.data) return <Skeleton className="h-64 w-full" />;
  const p = payment.data;
  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Payments to vendors", to: "/vendor-payments" },
          { label: `${formatDate(p.payment_date)} · ${p.vendor_name}` },
        ]}
      />
      <PageHeader
        title={`Paid to ${p.vendor_name}`}
        badges={p.status === "VOIDED" ? <StatusBadge status="voided" /> : undefined}
        description={`${formatDate(p.payment_date)} · ${MODE_LABELS[p.mode]}${p.reference ? ` · ${p.reference}` : ""}`}
      />
      <Card className="max-w-xl">
        <CardContent className="grid gap-3 text-sm">
          <p className="flex justify-between">
            <span className="text-muted-foreground">Amount</span>
            <Money value={p.amount} strong />
          </p>
          {p.allocations.length > 0 && (
            <ul aria-label="Bills it paid" className="grid gap-1">
              {p.allocations.map((a) => (
                <li key={a.id} className="flex justify-between">
                  <Link to={`/vendor-bills/${a.vendor_bill_id}`} className="underline">
                    {a.bill_number}
                  </Link>
                  <Money value={a.amount} />
                </li>
              ))}
            </ul>
          )}
          <p className="flex justify-between">
            <span className="text-muted-foreground">Left as an advance</span>
            <Money value={p.unallocated} />
          </p>
          {p.status === "VOIDED" && (
            <p className="text-muted-foreground">Voided: {p.void_reason}</p>
          )}
        </CardContent>
      </Card>
      {can(role, "payments.record") && p.status === "RECORDED" && (
        <div className="mt-4 max-w-xl">
          {voiding ? (
            <form
              aria-label="Void this payment"
              className="grid gap-3 rounded-md border p-3"
              onSubmit={(e) => {
                e.preventDefault();
                voidIt.mutate(p.version);
              }}
            >
              <label className="grid gap-1 text-sm">
                Why is it voided? (the bills it paid are owed again)
                <Input
                  value={reason}
                  onChange={(e) => {
                    setReason(e.target.value);
                  }}
                />
              </label>
              {voidIt.error && <p className="text-destructive text-sm">{voidIt.error.message}</p>}
              <div className="flex gap-2">
                <Button
                  type="submit"
                  variant="destructive"
                  disabled={voidIt.isPending || reason.trim().length < 3}
                >
                  Void the payment
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
          ) : (
            <Button
              variant="ghost"
              onClick={() => {
                setVoiding(true);
              }}
            >
              Void…
            </Button>
          )}
        </div>
      )}
    </>
  );
}
