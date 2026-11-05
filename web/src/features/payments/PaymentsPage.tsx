import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column, SortState } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { LoadMore } from "@/components/LoadMore";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SavedFilters } from "@/components/SavedFilters";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { formatDate } from "@/lib/dates";
import { compareMoney, sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import { MODE_LABELS } from "./modes";

type Mode = components["schemas"]["PaymentModeEnum"];
type Row = components["schemas"]["Payment"];
type Status = "" | "RECORDED" | "VOIDED";

const recorded = (p: Row) => p.status !== "VOIDED";

const columns: Column<Row>[] = [
  {
    id: "client",
    header: "Client / project",
    card: "title",
    cell: (p) => (
      <>
        <Link to={`/payments/${p.id}`} className="font-medium hover:underline">
          {p.party_name}
        </Link>
        {p.project_name && <div className="text-help text-muted-foreground">{p.project_name}</div>}
      </>
    ),
  },
  {
    id: "date",
    header: "Date",
    sortable: true,
    card: "subtitle",
    cell: (p) => formatDate(p.payment_date),
  },
  {
    id: "mode",
    header: "Mode",
    cell: (p) => (
      <>
        {MODE_LABELS[p.mode]}
        {p.reference && <div className="text-help text-muted-foreground">{p.reference}</div>}
      </>
    ),
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
    sortable: true,
    card: "amount",
    cell: (p) => <Money value={p.amount} muted={p.status === "VOIDED"} />,
  },
  {
    id: "unallocated",
    header: "Not set against bills",
    align: "right",
    card: "amount",
    cell: (p) =>
      recorded(p) && compareMoney(p.unallocated, "0") === 1 ? (
        <Money value={p.unallocated} />
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
];

/** Server orderings for the sortable columns (payments API: payment_date, amount). */
const ORDERING: Record<string, string> = { date: "payment_date", amount: "amount" };

interface Filters extends Record<string, string> {
  status: string;
  mode: string;
}
const NO_FILTERS: Filters = { status: "RECORDED", mode: "" };

export function PaymentsPage() {
  const mayRecord = can(useSession().role, "payments.record");
  const [status, setStatus] = useState<Status>("RECORDED");
  const [mode, setMode] = useState<Mode | "">("");
  const [sort, setSort] = useState<SortState>({ column: "date", direction: "desc" });
  const filtered = status !== "RECORDED" || mode !== "";
  const apply = (f: Filters) => {
    setStatus(f.status as Status);
    setMode(f.mode as Mode | "");
  };
  const payments = useInfiniteQuery({
    queryKey: ["payments", { status, mode, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/payments", {
          params: {
            query: {
              ...(status ? { status } : {}),
              ...(mode ? { mode } : {}),
              ordering: `${sort.direction === "desc" ? "-" : ""}${ORDERING[sort.column] ?? "payment_date"}`,
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
  const counted = rows.filter(recorded);
  const record = mayRecord ? (
    <Button asChild>
      <Link to="/payments/new">
        <Plus aria-hidden /> Record payment
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Payments"
        description="Money received from clients, and what it settled."
        actions={record}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <NativeSelect
          aria-label="Status"
          className="w-auto"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as Status);
          }}
        >
          <option value="RECORDED">Recorded</option>
          <option value="VOIDED">Voided</option>
          <option value="">All</option>
        </NativeSelect>
        <NativeSelect
          aria-label="Mode"
          className="w-auto"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as Mode | "");
          }}
        >
          <option value="">Any mode</option>
          {Object.entries(MODE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        <SavedFilters list="payments" current={{ status, mode }} onApply={apply} />
      </div>
      {payments.error ? (
        <ErrorState error={payments.error} />
      ) : (
        <>
          <DataTable
            label="Payments"
            rows={rows}
            columns={status === "RECORDED" ? columns.filter((c) => c.id !== "status") : columns}
            rowKey={(p) => p.id}
            rowLabel={(p) => `${p.party_name}, ${formatDate(p.payment_date)}`}
            loading={payments.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: "No payments match these filters",
                    action: (
                      <Button
                        variant="outline"
                        onClick={() => {
                          apply(NO_FILTERS);
                        }}
                      >
                        Clear the filters
                      </Button>
                    ),
                  }
                : {
                    title: "No payments yet",
                    description:
                      "Record money as it comes in, and set it against the bills it pays.",
                    action: record,
                  }
            }
            totals={
              counted.length > 1
                ? {
                    label: `Total of ${String(counted.length)} shown${counted.length < rows.length ? ", not counting voided" : ""}`,
                    cells: {
                      amount: <Money value={sumMoney(counted.map((p) => p.amount))} />,
                      unallocated: <Money value={sumMoney(counted.map((p) => p.unallocated))} />,
                    },
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
