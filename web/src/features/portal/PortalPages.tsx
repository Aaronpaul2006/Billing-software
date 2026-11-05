import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
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
import { DOC_TYPE_LABELS, STATUS_LABELS, statusVariant } from "@/features/documents/api";
import { formatInr, formatQty } from "@/lib/money";
import { formatDate } from "@/lib/dates";

import {
  BILL_TYPES,
  portalBoqQuery,
  portalDocumentsQuery,
  portalPaymentsQuery,
  portalProjectsQuery,
  portalStatementQuery,
} from "./api";
import type { PortalDocument } from "./api";

const day = (iso: string | null | undefined) => formatDate(iso, "");

function Loading() {
  return <Skeleton className="h-32 w-full" />;
}

function DocumentsTable({ rows }: { rows: PortalDocument[] }) {
  if (rows.length === 0) return <p className="text-muted-foreground text-sm">Nothing here yet.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Number</TableHead>
          <TableHead>Date</TableHead>
          <TableHead>Project</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Amount</TableHead>
          <TableHead className="text-right">Due</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((d) => (
          <TableRow key={d.id}>
            <TableCell>
              <Link to={`/portal/bills/${d.id}`} className="font-medium underline">
                {d.doc_number}
              </Link>
              <div className="text-muted-foreground text-xs">
                {DOC_TYPE_LABELS[d.doc_type]}
                {d.is_ra_bill && d.ra_sequence ? ` · RA bill ${d.ra_sequence}` : ""}
              </div>
            </TableCell>
            <TableCell>{day(d.doc_date)}</TableCell>
            <TableCell>{d.project_name}</TableCell>
            <TableCell>
              <Badge variant={statusVariant(d.status)}>{STATUS_LABELS[d.status]}</Badge>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatInr(d.totals.net_receivable)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {(BILL_TYPES as readonly string[]).includes(d.doc_type) && d.status === "ISSUED"
                ? formatInr(d.totals.outstanding)
                : ""}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
        <DocumentsTable rows={bills.data.results.slice(0, 5)} />
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
        <DocumentsTable rows={documents.data.results} />
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

export function PortalPaymentsPage() {
  const payments = useQuery(portalPaymentsQuery);
  return (
    <>
      <PageHeader title="Payments" description="Payments we have received from you." />
      {payments.isPending ? (
        <Loading />
      ) : payments.isError ? (
        <ErrorState error={payments.error} />
      ) : payments.data.results.length === 0 ? (
        <p className="text-muted-foreground text-sm">No payments yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Against</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {payments.data.results.map((p) => (
              <TableRow key={p.id}>
                <TableCell>{day(p.payment_date)}</TableCell>
                <TableCell>
                  {MODE_LABELS[p.mode] ?? p.mode}
                  {p.reference ? ` · ${p.reference}` : ""}
                </TableCell>
                <TableCell className="text-sm">
                  {p.allocations
                    .map((a) => `${a.doc_number ?? "Retention release"} ${formatInr(a.amount)}`)
                    .join(", ") || "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatInr(p.amount)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}

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
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Details</TableHead>
              <TableHead className="text-right">Billed</TableHead>
              <TableHead className="text-right">Paid / credited</TableHead>
              <TableHead className="text-right">Balance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell />
              <TableCell>Opening balance</TableCell>
              <TableCell />
              <TableCell />
              <TableCell className="text-right tabular-nums">
                {formatInr(statement.data.opening_balance)}
              </TableCell>
            </TableRow>
            {statement.data.entries.map((e, i) => (
              <TableRow key={`${e.date}-${i}`}>
                <TableCell>{day(e.date)}</TableCell>
                <TableCell>{e.description}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {e.debit !== "0.00" ? formatInr(e.debit) : ""}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {e.credit !== "0.00" ? formatInr(e.credit) : ""}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatInr(e.balance)}</TableCell>
              </TableRow>
            ))}
            <TableRow className="font-medium">
              <TableCell />
              <TableCell>Closing balance</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatInr(statement.data.total_debit)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatInr(statement.data.total_credit)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatInr(statement.data.closing_balance)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
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
