import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { DataTable } from "@/components/DataTable";
import type { Column, SortState } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { SavedFilters } from "@/components/SavedFilters";
import type { components } from "@/api/schema";
import { sumMoney } from "@/lib/money";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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

type Row = components["schemas"]["DocumentList"];

/** Bills that ask to be paid, once issued: they have something outstanding. */
const owed = (d: Row) => d.status === "ISSUED" && RECEIVABLE_TYPES.has(d.doc_type);

const columns: Column<Row>[] = [
  {
    id: "number",
    header: "Number",
    sortable: true,
    card: "title",
    cell: (d) => (
      <>
        <Link to={`/documents/${d.id}`} className="font-medium hover:underline">
          {d.doc_number ?? "Draft"}
        </Link>
        <div className="text-help text-muted-foreground">
          {DOC_TYPE_LABELS[d.doc_type]}
          {d.is_ra_bill && d.ra_sequence ? ` · RA ${String(d.ra_sequence)}` : ""}
        </div>
      </>
    ),
  },
  { id: "date", header: "Date", sortable: true, cell: (d) => formatDate(d.doc_date) },
  {
    id: "party",
    header: "Party / project",
    card: "subtitle",
    cell: (d) => (
      <>
        {d.party_name}
        {d.project_name && <div className="text-help text-muted-foreground">{d.project_name}</div>}
      </>
    ),
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (d) => <StatusBadge status={documentStatus(d)} />,
  },
  {
    id: "total",
    header: "Total",
    align: "right",
    card: "amount",
    cell: (d) => <Money value={d.totals.grand_total} />,
  },
  {
    id: "outstanding",
    header: "Outstanding",
    align: "right",
    card: "amount",
    cell: (d) =>
      owed(d) ? (
        <Money
          value={d.totals.outstanding}
          strong={d.totals.outstanding !== "0.00"}
          muted={d.totals.outstanding === "0.00"}
        />
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
];

/** Server orderings for the sortable columns (documents API: doc_date, doc_number). */
const ORDERING: Record<string, string> = { number: "doc_number", date: "doc_date" };

interface Filters extends Record<string, string> {
  type: string;
  status: string;
  paymentState: string;
  search: string;
}
const NO_FILTERS: Filters = { type: "all", status: "", paymentState: "", search: "" };

export function DocumentsPage() {
  const [type, setType] = useState("all");
  const [status, setStatus] = useState<DocStatus | "">("");
  const [paymentState, setPaymentState] = useState<PaymentState>("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState>({ column: "date", direction: "desc" });
  const filtered = type !== "all" || status !== "" || paymentState !== "" || search.trim() !== "";
  const apply = (f: Filters) => {
    setType(f.type);
    setStatus(f.status as DocStatus | "");
    setPaymentState(f.paymentState as PaymentState);
    setSearch(f.search);
  };
  const q = useDeferredValue(search.trim());
  const types = TYPE_FILTERS.find((t) => t.value === type)?.types ?? [];

  const documents = useInfiniteQuery({
    queryKey: ["documents", { type, status, paymentState, q, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/documents", {
          params: {
            query: {
              ...(types.length ? { doc_type: types } : {}),
              ...(status ? { status: [status] } : {}),
              ...(paymentState ? { payment_state: paymentState } : {}),
              ...(q ? { q } : {}),
              ordering: `${sort.direction === "desc" ? "-" : ""}${ORDERING[sort.column] ?? "doc_date"}`,
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
                <Plus aria-hidden /> New bill
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
        <SavedFilters
          list="bills"
          current={{ type, status, paymentState, search }}
          onApply={apply}
        />
      </div>

      {documents.error ? (
        <ErrorState error={documents.error} />
      ) : (
        <>
          <DataTable
            label="Bills and quotations"
            rows={rows}
            columns={columns}
            rowKey={(d) => d.id}
            rowLabel={(d) => d.doc_number ?? `draft for ${d.party_name}`}
            loading={documents.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: "No documents match these filters",
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
                    title: "No bills yet",
                    description:
                      "Make your first bill or quotation; drafts get their number when issued.",
                    action: (
                      <Button asChild>
                        <Link to="/documents/new">
                          <Plus aria-hidden /> New bill
                        </Link>
                      </Button>
                    ),
                  }
            }
            totals={
              rows.length > 1
                ? {
                    label: `Total of ${String(rows.length)} shown`,
                    cells: {
                      total: <Money value={sumMoney(rows.map((d) => d.totals.grand_total))} />,
                      outstanding: (
                        <Money
                          value={sumMoney(rows.filter(owed).map((d) => d.totals.outstanding))}
                        />
                      ),
                    },
                  }
                : undefined
            }
          />
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
