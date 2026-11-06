import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, IndianRupee, Pencil } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { CATEGORY_LABELS } from "@/features/expenses/labels";
import { formatDate } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { compareMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import { useVendorBill, vendorBillKey } from "./api";
import type { VendorBill } from "./api";
import { billStatus } from "./status";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

function VoidForm({ bill, onDone }: { bill: VendorBill; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const voidIt = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/vendor-bills/{bill_id}/void", {
          params: { path: { bill_id: bill.id } },
          body: { reason: reason.trim() },
          headers: { "If-Match": ifMatch(bill.version) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(vendorBillKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      onDone();
    },
  });
  return (
    <form
      aria-label="Void this bill"
      className="grid max-w-md gap-3 rounded-md border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        voidIt.mutate();
      }}
    >
      {voidIt.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{voidIt.error.message}</AlertDescription>
        </Alert>
      )}
      <label className="grid gap-1 text-sm">
        Why is it voided?
        <Input
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
        />
      </label>
      <div className="flex gap-2">
        <Button
          type="submit"
          variant="destructive"
          disabled={voidIt.isPending || reason.trim().length < 3}
        >
          Void the bill
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Keep it
        </Button>
      </div>
    </form>
  );
}

export function VendorBillPage() {
  const { billId = "" } = useParams();
  const bill = useVendorBill(billId);
  const { role } = useSession();
  const [voiding, setVoiding] = useState(false);
  if (bill.error) return <ErrorState error={bill.error} />;
  if (!bill.data) return <Skeleton className="h-96 w-full" />;
  const b = bill.data;
  const status = billStatus(b);
  const mayRecord = can(role, "payments.record");
  const owed = b.status === "RECORDED" && compareMoney(b.outstanding, "0") === 1;
  const paidSome = compareMoney(b.amount_paid, "0") === 1;
  return (
    <>
      <Breadcrumbs
        items={[{ label: "Vendor bills", to: "/vendor-bills" }, { label: b.bill_number }]}
      />
      <PageHeader
        title={`${b.vendor_name} · ${b.bill_number}`}
        badges={status ? <StatusBadge status={status} /> : undefined}
        description={`${CATEGORY_LABELS[b.category]}${b.project_name ? ` · ${b.project_name}` : ""} · ${b.description}`}
      />
      {mayRecord && b.status === "RECORDED" && (
        <div role="group" aria-label="Actions" className="mb-4 flex flex-wrap gap-2">
          {owed && (
            <Button asChild>
              <Link
                to={`/vendor-payments/new?vendor=${b.vendor_party_id}&name=${encodeURIComponent(b.vendor_name)}`}
              >
                <IndianRupee aria-hidden /> Pay this vendor
              </Link>
            </Button>
          )}
          {!paidSome && (
            <Button variant="outline" asChild>
              <Link to={`/vendor-bills/${b.id}/edit`}>
                <Pencil aria-hidden /> Edit
              </Link>
            </Button>
          )}
          {!voiding && (
            <Button
              variant="ghost"
              disabled={paidSome}
              title={paidSome ? "Void its payments first" : undefined}
              onClick={() => {
                setVoiding(true);
              }}
            >
              Void…
            </Button>
          )}
        </div>
      )}
      {voiding && (
        <div className="mb-4">
          <VoidForm
            bill={b}
            onDone={() => {
              setVoiding(false);
            }}
          />
        </div>
      )}
      {b.status === "VOIDED" && (
        <p className="text-muted-foreground mb-4 text-sm">Voided: {b.void_reason}</p>
      )}
      <Card className="max-w-xl">
        <CardContent>
          <dl className="text-sm">
            <Row label="Bill date">{formatDate(b.bill_date)}</Row>
            <Row label="Pay by">{b.due_date ? formatDate(b.due_date) : "–"}</Row>
            <Row label="Amount before GST">
              <Money value={b.taxable_value} />
            </Row>
            <Row label={`GST${b.itc_eligible ? " (we claim it)" : ""}`}>
              <Money value={b.gst_amount} />
            </Row>
            <Row label="Bill total">
              <Money value={b.total_amount} strong />
            </Row>
            <Row label={b.tds_section ? `Less TDS ${b.tds_section} at ${b.tds_rate} %` : "TDS"}>
              {b.tds_section ? (
                <>
                  − <Money value={b.tds_amount} />
                </>
              ) : (
                "none"
              )}
            </Row>
            <Row label="We pay the vendor">
              <Money value={b.net_payable} strong />
            </Row>
            <Row label="Paid so far">
              <Money value={b.amount_paid} />
            </Row>
            <Row label="Still to pay">
              <Money value={b.outstanding} strong={owed} />
            </Row>
          </dl>
          {paidSome && (
            <p className="text-help text-muted-foreground mt-3">
              <Link to={`/vendor-payments?vendor=${b.vendor_party_id}`} className="underline">
                See the payments to {b.vendor_name}
              </Link>
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
