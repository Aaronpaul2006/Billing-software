import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { compareMoney, formatInr } from "@/lib/money";
import { formatDate } from "@/lib/dates";

import { CATEGORY_LABELS } from "./labels";
import type { Category } from "./labels";

type PaymentState = "" | "UNPAID" | "PARTIAL" | "PAID";

export function ExpensesPage() {
  const [category, setCategory] = useState<Category | "">("");
  const [paymentState, setPaymentState] = useState<PaymentState>("");
  const [showVoided, setShowVoided] = useState(false);

  const expenses = useInfiniteQuery({
    queryKey: ["expenses", { category, paymentState, showVoided }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/expenses", {
          params: {
            query: {
              ...(category ? { category: [category] } : {}),
              ...(paymentState ? { payment_state: paymentState } : {}),
              status: showVoided ? "VOIDED" : "RECORDED",
              ordering: "-expense_date",
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

  return (
    <>
      <PageHeader
        title="Expenses"
        description="Site and office costs: they count against project margins."
        actions={
          <Button asChild>
            <Link to="/expenses/new">
              <Plus aria-hidden /> Record expense
            </Link>
          </Button>
        }
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
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showVoided}
            onChange={(e) => {
              setShowVoided(e.target.checked);
            }}
          />
          Voided
        </label>
      </div>
      {expenses.error ? (
        <ErrorState error={expenses.error} />
      ) : expenses.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">No expenses.</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Vendor / project</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">To pay</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((x) => (
                <TableRow key={x.id}>
                  <TableCell>{formatDate(x.expense_date)}</TableCell>
                  <TableCell className="max-w-80 whitespace-normal">
                    <Link to={`/expenses/${x.id}`} className="font-medium hover:underline">
                      {x.description}
                    </Link>
                    <div className="text-muted-foreground text-xs">
                      {CATEGORY_LABELS[x.category]}
                      {x.vendor_bill_number ? ` · bill ${x.vendor_bill_number}` : ""}
                    </div>
                  </TableCell>
                  <TableCell>
                    {x.vendor_name ?? "–"}
                    {x.project_name && (
                      <div className="text-muted-foreground text-xs">{x.project_name}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInr(x.total_amount)}
                    {x.itc_eligible && (
                      <Badge variant="outline" className="ml-2">
                        ITC
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {compareMoney(x.balance, "0") === 1 ? formatInr(x.balance) : "–"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {expenses.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={expenses.isFetchingNextPage}
                onClick={() => void expenses.fetchNextPage()}
              >
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
