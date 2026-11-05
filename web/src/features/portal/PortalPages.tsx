import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import type { components } from "@/api/schema";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { periodRange } from "@/features/dashboard/periods";
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import { formatInr, formatQty, sumMoney } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { StatusBadge } from "@/components/StatusBadge";
import { documentStatus } from "@/features/documents/status";

import {
  BILL_TYPES,
  portalBoqQuery,
  portalDocumentsQuery,
  portalPaymentsQuery,
  portalProjectsQuery,
  portalStatementQuery,
} from "./api";
import type { PortalDocument, PortalPayment } from "./api";

const day = (iso: string | null | undefined) => formatDate(iso, "");

function Loading() {
  return <Skeleton className="h-32 w-full" />;
}

const owedOn = (d: PortalDocument) =>
  (BILL_TYPES as readonly string[]).includes(d.doc_type) && d.status === "ISSUED";

const DOCUMENT_COLUMNS: Column<PortalDocument>[] = [
  {
    id: "number",
    header: "Number",
    card: "title",
    cell: (d) => (
      <>
        <Link to={`/portal/bills/${d.id}`} className="font-medium underline">
          {d.doc_number}
        </Link>
        <div className="text-help text-muted-foreground">
          {DOC_TYPE_LABELS[d.doc_type]}
          {d.is_ra_bill && d.ra_sequence ? ` · RA bill ${d.ra_sequence}` : ""}
        </div>
      </>
    ),
  },
  {
    id: "date",
    header: "Date",
    sortable: true,
    sortValue: (d) => d.doc_date,
    card: "subtitle",
    cell: (d) => day(d.doc_date),
  },
  { id: "project", header: "Project", cell: (d) => d.project_name ?? "–" },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (d) => <StatusBadge status={documentStatus(d)} />,
  },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "amount",
    cell: (d) => <Money value={d.totals.net_receivable} />,
  },
  {
    id: "due",
    header: "Due",
    align: "right",
    card: "amount",
    cell: (d) =>
      owedOn(d) ? (
        <Money value={d.totals.outstanding} strong={d.totals.outstanding !== "0.00"} />
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
];

function DocumentsTable({ rows, label }: { rows: PortalDocument[]; label: string }) {
  const owed = rows.filter(owedOn);
  return (
    <DataTable
      label={label}
      rows={rows}
      columns={DOCUMENT_COLUMNS}
      rowKey={(d) => d.id}
      rowLabel={(d) => d.doc_number ?? DOC_TYPE_LABELS[d.doc_type]}
      defaultSort={{ column: "date", direction: "desc" }}
      empty={{ title: "Nothing here yet" }}
      totals={
        owed.length > 1
          ? {
              label: `Still due on ${String(owed.length)} bills`,
              cells: { due: <Money value={sumMoney(owed.map((d) => d.totals.outstanding))} /> },
            }
          : undefined
      }
    />
  );
}

export function PortalHomePage() {
  const fy = periodRange("this_fy", new Date());
  const statement = useQuery(portalStatementQuery(fy.from, fy.to));
  const quotes = useQuery(portalDocumentsQuery(["QUOTATION"], ["ISSUED"]));
  const bills = useQuery(portalDocumentsQuery([...BILL_TYPES]));
  const balance = statement.data?.closing_balance;
  return (
    <>
      <PageHeader title="Overview" />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Balance</CardTitle>
          </CardHeader>
          <CardContent>
            {statement.isPending ? (
              <Skeleton className="h-8 w-40" />
            ) : statement.isError ? (
              <ErrorState error={statement.error} />
            ) : (
              <>
                <p className="text-3xl font-semibold tabular-nums">
                  {formatInr(balance?.replace(/^-/, ""))}
                </p>
                <p className="text-muted-foreground text-sm">
                  {balance?.startsWith("-") ? "Paid in advance" : "To pay"} ·{" "}
                  <Link to="/portal/statement" className="underline">
                    statement
                  </Link>
                </p>
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Quotations waiting for your answer</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            {quotes.isPending ? (
              <Skeleton className="h-8 w-full" />
            ) : quotes.isError ? (
              <ErrorState error={quotes.error} />
            ) : quotes.data.results.length === 0 ? (
              <p className="text-muted-foreground text-sm">None.</p>
            ) : (
              quotes.data.results.map((q) => (
                <Link
                  key={q.id}
                  to={`/portal/bills/${q.id}`}
                  className="flex justify-between gap-2 text-sm underline"
                >
                  <span>
                    {q.doc_number}
                    {q.valid_until ? ` · valid until ${day(q.valid_until)}` : ""}
                  </span>
                  <span className="tabular-nums">{formatInr(q.totals.grand_total)}</span>
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </div>
      <h2 className="mt-8 mb-2 text-lg font-semibold">Recent bills</h2>
      {bills.isPending ? (
        <Loading />
      ) : bills.isError ? (
        <ErrorState error={bills.error} />
      ) : (
        <DocumentsTable label="Recent bills" rows={bills.data.results.slice(0, 5)} />
      )}
    </>
  );
}

const FILTERS = {
  all: { label: "All", types: [] as string[] },
  bills: { label: "Bills", types: [...BILL_TYPES] },
  quotes: { label: "Quotations", types: ["QUOTATION"] },
  notes: { label: "Credit notes", types: ["CREDIT_NOTE"] },
} as const;

export function PortalDocumentsPage() {
  const [filter, setFilter] = useState<keyof typeof FILTERS>("all");
  const documents = useQuery(portalDocumentsQuery(FILTERS[filter].types));
  return (
    <>
      <PageHeader title="Bills & quotes" />
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Show">
        {(Object.keys(FILTERS) as (keyof typeof FILTERS)[]).map((key) => (
          <Button
            key={key}
            size="sm"
            variant={filter === key ? "default" : "outline"}
            aria-pressed={filter === key}
            onClick={() => {
              setFilter(key);
            }}
          >
            {FILTERS[key].label}
          </Button>
        ))}
      </div>
      {documents.isPending ? (
        <Loading />
      ) : documents.isError ? (
        <ErrorState error={documents.error} />
      ) : (
        <DocumentsTable label={FILTERS[filter].label} rows={documents.data.results} />
      )}
    </>
  );
}

const MODE_LABELS: Record<string, string> = {
  BANK_TRANSFER: "Bank transfer",
  UPI: "UPI",
  CHEQUE: "Cheque",
  CASH: "Cash",
  CARD: "Card",
  OTHER: "Other",
};

const PAYMENT_COLUMNS: Column<PortalPayment>[] = [
  {
    id: "date",
    header: "Date",
    sortable: true,
    sortValue: (p) => p.payment_date,
    card: "title",
    cell: (p) => <span className="font-medium">{day(p.payment_date)}</span>,
  },
  {
    id: "mode",
    header: "Mode",
    card: "subtitle",
    cell: (p) => `${MODE_LABELS[p.mode] ?? p.mode}${p.reference ? ` · ${p.reference}` : ""}`,
  },
  {
    id: "against",
    header: "Against",
    className: "whitespace-normal",
    cell: (p) =>
      p.allocations
        .map((x) => `${x.doc_number ?? "Retention release"} ${formatInr(x.amount)}`)
        .join(", ") || "–",
  },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "amount",
    cell: (p) => <Money value={p.amount} />,
  },
];

export function PortalPaymentsPage() {
  const payments = useQuery(portalPaymentsQuery);
  return (
    <>
      <PageHeader title="Payments" description="Payments we have received from you." />
      {payments.isPending ? (
        <Loading />
      ) : payments.isError ? (
        <ErrorState error={payments.error} />
      ) : (
        <DataTable
          label="Payments"
          rows={payments.data.results}
          columns={PAYMENT_COLUMNS}
          rowKey={(p) => p.id}
          rowLabel={(p) => day(p.payment_date)}
          defaultSort={{ column: "date", direction: "desc" }}
          empty={{ title: "No payments yet" }}
          totals={
            payments.data.results.length > 1
              ? {
                  label: `Total of ${String(payments.data.results.length)} payments`,
                  cells: {
                    amount: <Money value={sumMoney(payments.data.results.map((p) => p.amount))} />,
                  },
                }
              : undefined
          }
        />
      )}
    </>
  );
}

type StatementEntry = components["schemas"]["StatementEntry"];

const STATEMENT_COLUMNS: Column<StatementEntry>[] = [
  { id: "date", header: "Date", card: "subtitle", cell: (e) => day(e.date) },
  {
    id: "details",
    header: "Details",
    card: "title",
    className: "whitespace-normal",
    cell: (e) => e.description,
  },
  {
    id: "debit",
    header: "Billed",
    align: "right",
    card: "amount",
    cell: (e) => (e.debit !== "0.00" ? <Money value={e.debit} /> : null),
  },
  {
    id: "credit",
    header: "Paid / credited",
    align: "right",
    card: "amount",
    cell: (e) => (e.credit !== "0.00" ? <Money value={e.credit} /> : null),
  },
  {
    id: "balance",
    header: "Balance",
    align: "right",
    card: "amount",
    cell: (e) => <Money value={e.balance} />,
  },
];

export function PortalStatementPage() {
  const fy = periodRange("this_fy", new Date());
  const statement = useQuery(portalStatementQuery(fy.from, fy.to));
  return (
    <>
      <PageHeader
        title="Statement of account"
        description={`This financial year: ${day(fy.from)} to ${day(fy.to)}`}
      />
      {statement.isPending ? (
        <Loading />
      ) : statement.isError ? (
        <ErrorState error={statement.error} />
      ) : (
        <div className="grid gap-3">
          <p className="text-sm">
            Opening balance on {day(fy.from)}:{" "}
            <Money value={statement.data.opening_balance} strong />
          </p>
          <DataTable
            label="Statement of account"
            rows={statement.data.entries}
            columns={STATEMENT_COLUMNS}
            rowKey={(e) => `${e.date}-${e.description}-${e.balance}`}
            empty={{ title: "Nothing billed or paid this year yet" }}
            totals={{
              label: "Closing balance",
              cells: {
                debit: <Money value={statement.data.total_debit} />,
                credit: <Money value={statement.data.total_credit} />,
                balance: <Money value={statement.data.closing_balance} strong />,
              },
            }}
          />
        </div>
      )}
    </>
  );
}

export function PortalProjectsPage() {
  const projects = useQuery(portalProjectsQuery);
  return (
    <>
      <PageHeader title="Projects" />
      {projects.isPending ? (
        <Loading />
      ) : projects.isError ? (
        <ErrorState error={projects.error} />
      ) : projects.data.results.length === 0 ? (
        <p className="text-muted-foreground text-sm">No projects.</p>
      ) : (
        <div className="grid gap-2">
          {projects.data.results.map((p) => (
            <Link
              key={p.id}
              to={`/portal/projects/${p.id}`}
              className="hover:bg-accent flex justify-between gap-2 rounded-md border p-3"
            >
              <span>
                <span className="font-medium">{p.name}</span>{" "}
                <span className="text-muted-foreground text-sm">{p.code}</span>
              </span>
              {p.contract_value && (
                <span className="tabular-nums">{formatInr(p.contract_value)}</span>
              )}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function PortalProjectPage() {
  const { projectId = "" } = useParams();
  const progress = useQuery(portalBoqQuery(projectId));
  const project = useQuery(portalProjectsQuery).data?.results.find((p) => p.id === projectId);
  return (
    <>
      <PageHeader
        title={project?.name ?? "Project"}
        description="Work done so far against the contract (bill of quantities)."
      />
      {progress.isPending ? (
        <Loading />
      ) : progress.isError ? (
        <ErrorState error={progress.error} />
      ) : progress.data.results.length === 0 ? (
        <p className="text-muted-foreground text-sm">No bill of quantities for this project.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Contract</TableHead>
              <TableHead className="text-right">Billed</TableHead>
              <TableHead className="text-right">Done</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {progress.data.results.map((r) => (
              <TableRow key={r.boq_item_id}>
                <TableCell>
                  <span className="text-muted-foreground mr-1 text-xs">{r.item_code}</span>
                  {r.description}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatQty(r.contract_qty)} {r.unit}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatQty(r.billed_qty)} {r.unit}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {r.progress_pct == null ? "" : `${r.progress_pct} %`}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
