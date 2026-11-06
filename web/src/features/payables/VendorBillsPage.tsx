import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { CATEGORY_LABELS } from "@/features/expenses/labels";
import { formatDate } from "@/lib/dates";
import { compareMoney, sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import type { VendorBill } from "./api";
import { billStatus } from "./status";

type PaymentState = "" | "OPEN" | "UNPAID" | "PARTIAL" | "PAID";

const columns: Column<VendorBill>[] = [
  {
    id: "vendor",
    header: "Vendor / bill",
    card: "title",
    cell: (b) => (
      <>
        <Link to={`/vendor-bills/${b.id}`} className="font-medium hover:underline">
          {b.vendor_name}
        </Link>
        <div className="text-help text-muted-foreground">
          {b.bill_number} · {CATEGORY_LABELS[b.category]}
          {b.project_name ? ` · ${b.project_name}` : ""}
        </div>
      </>
    ),
  },
  {
    id: "date",
    header: "Date",
    sortable: true,
    card: "subtitle",
    cell: (b) => formatDate(b.bill_date),
  },
  {
    id: "due",
    header: "Due",
    sortable: true,
    cell: (b) => (b.due_date ? formatDate(b.due_date) : "–"),
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (b) => {
      const s = billStatus(b);
      return s ? <StatusBadge status={s} /> : null;
    },
  },
  {
    id: "total",
    header: "Bill total",
    align: "right",
    sortable: true,
    cell: (b) => <Money value={b.total_amount} />,
  },
  {
    id: "tds",
    header: "TDS",
    align: "right",
    cell: (b) =>
      b.tds_section ? (
        <span title={`${b.tds_section} at ${b.tds_rate} %`}>
          <Money value={b.tds_amount} />
        </span>
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
  {
    id: "outstanding",
    header: "To pay",
    align: "right",
    card: "amount",
    cell: (b) =>
      compareMoney(b.outstanding, "0") === 1 ? (
        <Money value={b.outstanding} strong />
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
];

const ORDERING: Record<string, string> = {
  date: "bill_date",
  due: "due_date",
  total: "total_amount",
};

interface Filters extends Record<string, string> {
  search: string;
  paymentState: string;
  voided: string;
}
const NO_FILTERS: Filters = { search: "", paymentState: "", voided: "" };

/** What we owe vendors, by age (owners, admins, accountants, viewers). */
function OweSummary() {
  const report = useQuery({
    queryKey: ["reports", "payables"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/payables")),
  });
  if (!report.data || report.data.results.length === 0) return null;
  const t = report.data.totals;
  const late = sumMoney([t.days_1_30, t.days_31_60, t.days_61_90, t.days_90_plus]);
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle>
          <h2>What we owe</h2>
        </CardTitle>
        <CardDescription>
          {t.bill_count} {t.bill_count === 1 ? "bill" : "bills"} to {report.data.results.length}{" "}
          {report.data.results.length === 1 ? "vendor" : "vendors"}, after the TDS we deduct.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-muted-foreground text-sm">To pay</p>
          <p className="text-figure font-semibold">
            <Money value={t.total} />
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-sm">Past the due date</p>
          <p className="text-figure font-semibold">
            <Money value={late} />
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-sm">Most owed to</p>
          <p className="font-medium">{report.data.results[0]?.display_name}</p>
          <p className="text-help text-muted-foreground">
            <Money value={report.data.results[0]?.total} />
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export function VendorBillsPage() {
  const { role } = useSession();
  const mayRecord = can(role, "payments.record");
  const [search, setSearch] = useState("");
  const [paymentState, setPaymentState] = useState<PaymentState>("");
  const [voided, setVoided] = useState(false);
  const [sort, setSort] = useState<SortState>({ column: "date", direction: "desc" });
  const q = useDeferredValue(search.trim());
  const filtered = search.trim() !== "" || paymentState !== "" || voided;
  const apply = (f: Filters) => {
    setSearch(f.search);
    setPaymentState(f.paymentState as PaymentState);
    setVoided(f.voided === "yes");
  };
  const bills = useInfiniteQuery({
    queryKey: ["vendor-bills", { q, paymentState, voided, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/vendor-bills", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...(paymentState ? { payment_state: paymentState } : {}),
              status: voided ? "VOIDED" : "RECORDED",
              ordering: `${sort.direction === "desc" ? "-" : ""}${ORDERING[sort.column] ?? "bill_date"}`,
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = bills.data?.pages.flatMap((p) => p.results) ?? [];
  const record = mayRecord ? (
    <Button asChild>
      <Link to="/vendor-bills/new">
        <Plus aria-hidden /> Record vendor bill
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Vendor bills"
        description="Bills from vendors and subcontractors: what they charge, the TDS we deduct, what we still owe."
        actions={
          <>
            {mayRecord && (
              <Button variant="outline" asChild>
                <Link to="/vendor-payments/new">Pay a vendor</Link>
              </Button>
            )}
            {record}
          </>
        }
      />
      {can(role, "reports.view") && <OweSummary />}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            type="search"
            placeholder="Search by vendor or bill number"
            aria-label="Search vendor bills"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </div>
        <NativeSelect
          aria-label="Paid"
          className="w-auto"
          value={paymentState}
          onChange={(e) => {
            setPaymentState(e.target.value as PaymentState);
          }}
        >
          <option value="">Paid or not</option>
          <option value="OPEN">Still to pay</option>
          <option value="UNPAID">Unpaid</option>
          <option value="PARTIAL">Part paid</option>
          <option value="PAID">Paid</option>
        </NativeSelect>
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={voided}
            onChange={(e) => {
              setVoided(e.target.checked);
            }}
          />
          Voided
        </label>
        <SavedFilters
          list="vendor-bills"
          current={{ search, paymentState, voided: voided ? "yes" : "" }}
          onApply={apply}
        />
      </div>
      {bills.error ? (
        <ErrorState error={bills.error} />
      ) : (
        <>
          <DataTable
            label="Vendor bills"
            rows={rows}
            columns={columns}
            rowKey={(b) => b.id}
            rowLabel={(b) => `${b.vendor_name} ${b.bill_number}`}
            loading={bills.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: "No vendor bills match these filters",
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
                    title: "No vendor bills yet",
                    description:
                      "Record the bills your vendors and subcontractors send; TDS is suggested for you.",
                    action: record,
                  }
            }
            totals={
              rows.length > 1 && !voided
                ? {
                    label: `Total of ${String(rows.length)} shown`,
                    cells: {
                      total: <Money value={sumMoney(rows.map((b) => b.total_amount))} />,
                      tds: <Money value={sumMoney(rows.map((b) => b.tds_amount))} />,
                      outstanding: <Money value={sumMoney(rows.map((b) => b.outstanding))} />,
                    },
                  }
                : undefined
            }
          />
          <LoadMore query={bills} />
        </>
      )}
    </>
  );
}
