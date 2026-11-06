import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FilePlus, Pencil } from "lucide-react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { formatQty } from "@/lib/money";
import { can } from "@/lib/permissions";

import { useWorkOrder, workOrderKey } from "./api";
import { RetentionPanel } from "./RetentionPanel";
import type { WorkOrderDetail, WorkOrderItem } from "./api";
import { billedPercent } from "./status";
import { WorkOrderBadge } from "./WorkOrdersPage";

type RaBill = WorkOrderDetail["ra_bills"][number];

const itemColumns: Column<WorkOrderItem>[] = [
  {
    id: "item",
    header: "Item",
    card: "title",
    cell: (i) => (
      <>
        <span className="font-medium">
          {i.item_code} · {i.description}
        </span>
        {i.boq_item_code && (
          <div className="text-help text-muted-foreground">Client BOQ {i.boq_item_code}</div>
        )}
      </>
    ),
  },
  {
    id: "qty",
    header: "Agreed",
    align: "right",
    card: "detail",
    cell: (i) => `${formatQty(i.qty)} ${i.unit}`,
  },
  {
    id: "rate",
    header: "Rate",
    align: "right",
    card: "detail",
    cell: (i) => <Money value={i.rate} />,
  },
  {
    id: "billed",
    header: "Billed",
    align: "right",
    card: "detail",
    cell: (i) => `${formatQty(i.billed_qty)} ${i.unit}`,
  },
  {
    id: "balance",
    header: "Left",
    align: "right",
    card: "amount",
    cell: (i) => `${formatQty(i.balance_qty)} ${i.unit}`,
  },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "detail",
    cell: (i) => <Money value={i.amount} />,
  },
];

const billColumns: Column<RaBill>[] = [
  {
    id: "ra",
    header: "RA bill",
    card: "title",
    cell: (b) => (
      <Link to={`/vendor-bills/${b.id}`} className="font-medium hover:underline">
        RA {b.ra_number} · {b.bill_number}
      </Link>
    ),
  },
  { id: "date", header: "Date", card: "subtitle", cell: (b) => formatDate(b.bill_date) },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (b) =>
      b.status === "VOIDED" ? (
        <StatusBadge status="voided" />
      ) : b.amount_paid === b.net_payable ? (
        <StatusBadge status="paid" />
      ) : b.amount_paid !== "0.00" ? (
        <StatusBadge status="part_paid" />
      ) : (
        <StatusBadge status="issued">To pay</StatusBadge>
      ),
  },
  {
    id: "value",
    header: "Value",
    align: "right",
    card: "detail",
    cell: (b) => <Money value={b.taxable_value} />,
  },
  {
    id: "retention",
    header: "Retention",
    align: "right",
    card: "detail",
    cell: (b) => <Money value={b.retention_amount} />,
  },
  {
    id: "net",
    header: "We pay",
    align: "right",
    card: "amount",
    cell: (b) => <Money value={b.net_payable} />,
  },
];

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="text-figure font-semibold">{children}</p>
    </div>
  );
}

export function WorkOrderPage() {
  const { workOrderId = "" } = useParams();
  const { role } = useSession();
  const queryClient = useQueryClient();
  const order = useWorkOrder(workOrderId);
  const toggle = useMutation({
    mutationFn: async (wo: WorkOrderDetail) => {
      const params = { path: { wo_id: wo.id } };
      const headers = { "If-Match": ifMatch(wo.version) };
      return unwrap(
        wo.status === "OPEN"
          ? await api.POST("/api/v1/work-orders/{wo_id}/close", { params, headers })
          : await api.POST("/api/v1/work-orders/{wo_id}/reopen", { params, headers }),
      );
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(workOrderKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["work-orders"] });
    },
  });
  if (order.error) return <ErrorState error={order.error} />;
  if (!order.data) return <Skeleton className="h-96 w-full" />;
  const wo = order.data;
  const mayRecord = can(role, "payments.record");
  const open = wo.status === "OPEN";
  return (
    <>
      <Breadcrumbs
        items={[{ label: "Work orders", to: "/work-orders" }, { label: wo.wo_number }]}
      />
      <PageHeader
        title={`${wo.wo_number} · ${wo.vendor_name}`}
        badges={<WorkOrderBadge status={wo.status} />}
        description={`${wo.title} · ${wo.project_code} ${wo.project_name} · ${formatDate(wo.wo_date)}`}
      />
      {mayRecord && (
        <div role="group" aria-label="Actions" className="mb-4 flex flex-wrap gap-2">
          {open && (
            <Button asChild>
              <Link to={`/work-orders/${wo.id}/ra-bills/new`}>
                <FilePlus aria-hidden /> Record RA bill
              </Link>
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to={`/work-orders/${wo.id}/edit`}>
              <Pencil aria-hidden /> Edit or amend
            </Link>
          </Button>
          <Button
            variant="ghost"
            disabled={toggle.isPending}
            onClick={() => {
              toggle.mutate(wo);
            }}
          >
            {open ? "Close the work order" : "Reopen"}
          </Button>
        </div>
      )}
      {toggle.error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle aria-hidden />
          <AlertDescription>{toggle.error.message}</AlertDescription>
        </Alert>
      )}
      <Card className="mb-4">
        <CardContent className="grid gap-4 @container sm:grid-cols-2 lg:grid-cols-4">
          <Figure label="Work order value">
            <Money value={wo.value} />
          </Figure>
          <Figure label={`Billed so far (${String(billedPercent(wo))} %)`}>
            <Money value={wo.billed} />
          </Figure>
          <Figure label={`Retention held (${String(Number(wo.retention_pct))} %)`}>
            <Money value={wo.retention_held} />
          </Figure>
          <Figure label="Paid on its bills">
            <Money value={wo.paid} />
          </Figure>
        </CardContent>
      </Card>
      <h2 className="text-section mb-2">Items</h2>
      <DataTable
        label="Work order items"
        rows={wo.items}
        columns={itemColumns}
        rowKey={(i) => i.id}
        rowLabel={(i) => `${i.item_code} ${i.description}`}
        totals={{ label: "Total", cells: { amount: <Money value={wo.value} /> } }}
      />
      <h2 className="text-section mt-6 mb-2">RA bills</h2>
      <DataTable
        label="RA bills"
        rows={wo.ra_bills}
        columns={billColumns}
        rowKey={(b) => b.id}
        rowLabel={(b) => `RA ${String(b.ra_number ?? "")} ${b.bill_number}`}
        empty={{
          title: "No RA bills yet",
          description: open
            ? "Record the subcontractor's first RA bill when it comes in."
            : undefined,
        }}
      />
      <RetentionPanel wo={wo} mayRecord={mayRecord} />
      <p className="text-help text-muted-foreground mt-3">
        {wo.tds_section
          ? `TDS ${wo.tds_section} at ${String(Number(wo.tds_rate))} % is deducted from each bill.`
          : "No TDS is deducted."}{" "}
        {wo.terms}
      </p>
    </>
  );
}
