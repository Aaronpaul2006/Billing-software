import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { LoadMore } from "@/components/LoadMore";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { MODE_LABELS } from "@/features/payments/modes";
import { formatDate } from "@/lib/dates";
import { sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import type { VendorPayment } from "./api";

const columns: Column<VendorPayment>[] = [
  {
    id: "vendor",
    header: "Vendor",
    card: "title",
    cell: (p) => (
      <>
        <Link to={`/vendor-payments/${p.id}`} className="font-medium hover:underline">
          {p.vendor_name}
        </Link>
        {p.allocations.length > 0 && (
          <div className="text-help text-muted-foreground">
            for {p.allocations.map((a) => a.bill_number).join(", ")}
          </div>
        )}
      </>
    ),
  },
  { id: "date", header: "Date", card: "subtitle", cell: (p) => formatDate(p.payment_date) },
  {
    id: "mode",
    header: "Mode",
    cell: (p) => `${MODE_LABELS[p.mode]}${p.reference ? ` · ${p.reference}` : ""}`,
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (p) => (p.status === "VOIDED" ? <StatusBadge status="voided" /> : null),
  },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "amount",
    cell: (p) => <Money value={p.amount} muted={p.status === "VOIDED"} />,
  },
];

export function VendorPaymentsPage() {
  const { role } = useSession();
  const [params] = useSearchParams();
  const vendor = params.get("vendor") ?? "";
  const payments = useInfiniteQuery({
    queryKey: ["vendor-payments", { vendor }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/vendor-payments", {
          params: {
            query: {
              ...(vendor ? { vendor_party_id: vendor } : {}),
              ordering: "-payment_date",
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = payments.data?.pages.flatMap((p) => p.results) ?? [];
  const recorded = rows.filter((p) => p.status === "RECORDED");
  const pay = can(role, "payments.record") ? (
    <Button asChild>
      <Link to="/vendor-payments/new">
        <Plus aria-hidden /> Pay a vendor
      </Link>
    </Button>
  ) : undefined;
  return (
    <>
      <PageHeader
        title="Payments to vendors"
        description="Money we paid vendors and subcontractors, and the bills it settled."
        actions={pay}
      />
      {payments.error ? (
        <ErrorState error={payments.error} />
      ) : (
        <>
          <DataTable
            label="Payments to vendors"
            rows={rows}
            columns={columns}
            rowKey={(p) => p.id}
            rowLabel={(p) => `${p.vendor_name}, ${formatDate(p.payment_date)}`}
            loading={payments.isPending}
            defaultSort={{ column: "date", direction: "desc" }}
            empty={{
              title: vendor ? "No payments to this vendor yet" : "No payments to vendors yet",
              action: pay,
            }}
            totals={
              recorded.length > 1
                ? {
                    label: `Total of ${String(recorded.length)} shown`,
                    cells: { amount: <Money value={sumMoney(recorded.map((p) => p.amount))} /> },
                  }
                : undefined
            }
          />
          <LoadMore query={payments} />
        </>
      )}
    </>
  );
}
