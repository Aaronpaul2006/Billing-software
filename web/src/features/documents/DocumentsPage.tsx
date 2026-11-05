import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/dates";
import { StatusBadge } from "@/components/StatusBadge";
import { documentStatus } from "@/features/documents/status";

import { DOC_TYPE_LABELS, RECEIVABLE_TYPES, STATUS_LABELS } from "./api";
import type { DocStatus, DocType } from "./api";

const TYPE_FILTERS: { value: string; label: string; types: DocType[] }[] = [
  { value: "all", label: "All documents", types: [] },
  {
    value: "invoices",
    label: "Invoices & bills of supply",
    types: ["TAX_INVOICE", "BILL_OF_SUPPLY"],
  },
  { value: "quotations", label: "Quotations", types: ["QUOTATION"] },
  { value: "proformas", label: "Proformas", types: ["PROFORMA"] },
  { value: "notes", label: "Credit & debit notes", types: ["CREDIT_NOTE", "DEBIT_NOTE"] },
];

type PaymentState = "" | "UNPAID" | "PARTIAL" | "PAID";

export function DocumentsPage() {
  const [type, setType] = useState("all");
  const [status, setStatus] = useState<DocStatus | "">("");
  const [paymentState, setPaymentState] = useState<PaymentState>("");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const types = TYPE_FILTERS.find((t) => t.value === type)?.types ?? [];

  const documents = useInfiniteQuery({
    queryKey: ["documents", { type, status, paymentState, q }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/documents", {
          params: {
            query: {
              ...(types.length ? { doc_type: types } : {}),
              ...(status ? { status: [status] } : {}),
              ...(paymentState ? { payment_state: paymentState } : {}),
              ...(q ? { q } : {}),
              ordering: "-doc_date",
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = documents.data?.pages.flatMap((p) => p.results) ?? [];

  return (
    <>
      <PageHeader
        title="Invoices & quotes"
        description="Drafts get their number when issued."
        actions={
          <>
            <Button variant="ghost" asChild>
              <Link to="/templates">From a template</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/documents/new?type=QUOTATION">New quotation</Link>
            </Button>
            <Button asChild>
              <Link to="/documents/new">
                <Plus aria-hidden /> New invoice
              </Link>
            </Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            type="search"
            placeholder="Search by number"
            aria-label="Search documents"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </div>
        <NativeSelect
          aria-label="Type"
          className="w-auto"
          value={type}
          onChange={(e) => {
            setType(e.target.value);
          }}
        >
          {TYPE_FILTERS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="Status"
          className="w-auto"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as DocStatus | "");
          }}
        >
          <option value="">Any status</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="Payment"
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
      </div>

      {documents.error ? (
        <ErrorState error={documents.error} />
      ) : documents.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">No documents match.</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Number</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Party / project</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => {
                const owed = d.status === "ISSUED" && RECEIVABLE_TYPES.has(d.doc_type);
                return (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link to={`/documents/${d.id}`} className="font-medium hover:underline">
                        {d.doc_number ?? "Draft"}
                      </Link>
                      <div className="text-muted-foreground text-xs">
                        {DOC_TYPE_LABELS[d.doc_type]}
                        {d.is_ra_bill && d.ra_sequence ? ` · RA ${String(d.ra_sequence)}` : ""}
                      </div>
                    </TableCell>
                    <TableCell>{formatDate(d.doc_date)}</TableCell>
                    <TableCell>
                      {d.party_name}
                      {d.project_name && (
                        <div className="text-muted-foreground text-xs">{d.project_name}</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={documentStatus(d)} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatInr(d.totals.grand_total)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        owed && d.totals.outstanding !== "0.00"
                          ? "font-medium"
                          : "text-muted-foreground",
                      )}
                    >
                      {owed ? formatInr(d.totals.outstanding) : "–"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {documents.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={documents.isFetchingNextPage}
                onClick={() => void documents.fetchNextPage()}
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
