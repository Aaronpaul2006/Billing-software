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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { formatDate } from "@/lib/dates";
import { compareMoney, sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import { CATEGORY_LABELS } from "./labels";
import type { Category } from "./labels";

type PaymentState = "" | "UNPAID" | "PARTIAL" | "PAID";
type Row = components["schemas"]["Expense"];

const columns: Column<Row>[] = [
  {
    id: "description",
    header: "Description",
    card: "title",
    className: "max-w-80 whitespace-normal",
    cell: (x) => (
      <>
        <Link to={`/expenses/${x.id}`} className="font-medium hover:underline">
          {x.description}
        </Link>
        <div className="text-help text-muted-foreground">
          {CATEGORY_LABELS[x.category]}
          {x.vendor_bill_number ? ` · bill ${x.vendor_bill_number}` : ""}
        </div>
      </>
    ),
  },
  {
    id: "date",
    header: "Date",
    sortable: true,
    card: "subtitle",
    cell: (x) => formatDate(x.expense_date),
  },
  {
    id: "vendor",
    header: "Vendor / project",
    cell: (x) => (
      <>
        {x.vendor_name ?? "–"}
        {x.project_name && <div className="text-help text-muted-foreground">{x.project_name}</div>}
      </>
    ),
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (x) =>
      x.status === "VOIDED" ? (
        <StatusBadge status="voided" />
      ) : x.itc_eligible ? (
        <Badge variant="outline" title="GST on it can be claimed as input tax credit">
          ITC
        </Badge>
      ) : null,
  },
  {
    id: "total",
    header: "Total",
    align: "right",
    sortable: true,
    card: "amount",
    cell: (x) => <Money value={x.total_amount} />,
  },
  {
    id: "balance",
    header: "To pay",
    align: "right",
    card: "amount",
    cell: (x) =>
      compareMoney(x.balance, "0") === 1 ? (
        <Money value={x.balance} strong />
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
];

/** Server orderings for the sortable columns (expenses API: expense_date, total_amount). */
const ORDERING: Record<string, string> = { date: "expense_date", total: "total_amount" };

interface Filters extends Record<string, string> {
  category: string;
  paymentState: string;
  voided: string;
}
const NO_FILTERS: Filters = { category: "", paymentState: "", voided: "" };

export function ExpensesPage() {
  const mayRecord = can(useSession().role, "expenses.record");
  const [category, setCategory] = useState<Category | "">("");
  const [paymentState, setPaymentState] = useState<PaymentState>("");
  const [showVoided, setShowVoided] = useState(false);
  const [sort, setSort] = useState<SortState>({ column: "date", direction: "desc" });
  const filtered = category !== "" || paymentState !== "" || showVoided;
  const apply = (f: Filters) => {
    setCategory(f.category as Category | "");
    setPaymentState(f.paymentState as PaymentState);
    setShowVoided(f.voided === "yes");
  };

  const expenses = useInfiniteQuery({
    queryKey: ["expenses", { category, paymentState, showVoided, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/expenses", {
          params: {
            query: {
              ...(category ? { category: [category] } : {}),
              ...(paymentState ? { payment_state: paymentState } : {}),
              status: showVoided ? "VOIDED" : "RECORDED",
              ordering: `${sort.direction === "desc" ? "-" : ""}${ORDERING[sort.column] ?? "expense_date"}`,
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = expenses.data?.pages.flatMap((p) => p.results) ?? [];
  const record = mayRecord ? (
    <Button asChild>
      <Link to="/expenses/new">
        <Plus aria-hidden /> Record expense
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Expenses"
        description="Site and office costs: they count against project margins."
        actions={record}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <NativeSelect
          aria-label="Category"
          className="w-auto"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value as Category | "");
          }}
        >
          <option value="">All categories</option>
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="Paid"
          className="w-auto"
          value={paymentState}
          onChange={(e) => {
            setPaymentState(e.target.value as PaymentState);
          }}
        >
          <option value="">Paid or not</option>
          <option value="UNPAID">Unpaid</option>
          <option value="PARTIAL">Part paid</option>
          <option value="PAID">Paid</option>
        </NativeSelect>
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showVoided}
            onChange={(e) => {
              setShowVoided(e.target.checked);
            }}
          />
          Voided
        </label>
        <SavedFilters
          list="expenses"
          current={{ category, paymentState, voided: showVoided ? "yes" : "" }}
          onApply={apply}
        />
      </div>
      {expenses.error ? (
        <ErrorState error={expenses.error} />
      ) : (
        <>
          <DataTable
            label="Expenses"
            rows={rows}
            columns={columns}
            rowKey={(x) => x.id}
            rowLabel={(x) => x.description}
            loading={expenses.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: "No expenses match these filters",
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
                    title: "No expenses yet",
                    description: "Record site and office costs to see each project's real margin.",
                    action: record,
                  }
            }
            totals={
              rows.length > 1 && !showVoided
                ? {
                    label: `Total of ${String(rows.length)} shown`,
                    cells: {
                      total: <Money value={sumMoney(rows.map((x) => x.total_amount))} />,
                      balance: <Money value={sumMoney(rows.map((x) => x.balance))} />,
                    },
                  }
                : undefined
            }
          />
          <LoadMore query={expenses} />
        </>
      )}
    </>
  );
}
