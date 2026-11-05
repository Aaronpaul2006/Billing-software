import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
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
import { StatusBadge } from "@/components/StatusBadge";

import { MODE_LABELS } from "./modes";

type Mode = components["schemas"]["PaymentModeEnum"];

export function PaymentsPage() {
  const [status, setStatus] = useState<"" | "RECORDED" | "VOIDED">("RECORDED");
  const [mode, setMode] = useState<Mode | "">("");
  const payments = useInfiniteQuery({
    queryKey: ["payments", { status, mode }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/payments", {
          params: {
            query: {
              ...(status ? { status } : {}),
              ...(mode ? { mode } : {}),
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

  return (
    <>
      <PageHeader
        title="Payments"
        description="Money received from clients, and what it settled."
        actions={
          <Button asChild>
            <Link to="/payments/new">
              <Plus aria-hidden /> Record payment
            </Link>
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <NativeSelect
          aria-label="Status"
          className="w-auto"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as typeof status);
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
      </div>
      {payments.error ? (
        <ErrorState error={payments.error} />
      ) : payments.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">No payments.</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Client</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead className="text-right">Unallocated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link to={`/payments/${p.id}`} className="font-medium hover:underline">
                      {formatDate(p.payment_date)}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {p.party_name}
                    {p.project_name && (
                      <div className="text-muted-foreground text-xs">{p.project_name}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    {MODE_LABELS[p.mode]}
                    {p.reference && (
                      <div className="text-muted-foreground text-xs">{p.reference}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInr(p.amount)}
                    {p.status === "VOIDED" && <StatusBadge status="voided" className="ml-2" />}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {compareMoney(p.unallocated, "0") === 1 ? formatInr(p.unallocated) : "–"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {payments.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={payments.isFetchingNextPage}
                onClick={() => void payments.fetchNextPage()}
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
