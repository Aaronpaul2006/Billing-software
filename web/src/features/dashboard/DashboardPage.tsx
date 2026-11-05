import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import type { DocType } from "@/features/documents/api";
import { errorMessage } from "@/lib/errors";
import { formatInr, toPaise } from "@/lib/money";
import { cn } from "@/lib/utils";
import { formatDayMonth } from "@/lib/dates";

import { formatRange, PERIOD_LABELS, periodRange } from "./periods";
import { Welcome } from "./Welcome";
import type { PeriodKey } from "./periods";

type Book = "ALL" | "GST" | "NON_GST";
type Dashboard = components["schemas"]["Dashboard"];
type Month = components["schemas"]["DashboardMonth"];
type OverdueRow = components["schemas"]["DashboardOverdueRow"];
type Receivable = components["schemas"]["Receivable"];

const BOOKS: { value: Book; label: string }[] = [
  { value: "ALL", label: "All books" },
  { value: "GST", label: "GST" },
  { value: "NON_GST", label: "Non-GST" },
];

const BUCKETS: { key: keyof Receivable; label: string }[] = [
  { key: "not_due", label: "Not due" },
  { key: "days_1_30", label: "1–30 days" },
  { key: "days_31_60", label: "31–60" },
  { key: "days_61_90", label: "61–90" },
  { key: "days_90_plus", label: "90+" },
];

function StatCard({
  title,
  value,
  previous,
  note,
}: {
  title: string;
  value: string | undefined;
  previous?: string | undefined;
  note?: string;
}) {
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">
          {value === undefined ? <Skeleton className="h-7 w-32" /> : formatInr(value)}
        </CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground px-4 text-xs">
        {note ?? (previous !== undefined ? `Previous period: ${formatInr(previous)}` : " ")}
      </CardContent>
    </Card>
  );
}

function Summary({ data }: { data: Dashboard | undefined }) {
  const now = data?.totals;
  const before = data?.previous;
  const overdueCount = data?.overdue.count ?? 0;
  return (
    <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <StatCard title="Billed" value={now?.billed} previous={before?.billed} />
      <StatCard title="Collected" value={now?.collected} previous={before?.collected} />
      <StatCard title="Outstanding" value={now?.outstanding} note="Owed to you today" />
      <StatCard
        title="Overdue"
        value={now?.overdue}
        note={`${overdueCount} ${overdueCount === 1 ? "bill" : "bills"} past due`}
      />
      <StatCard title="Expenses" value={now?.expenses} previous={before?.expenses} />
      <StatCard title="Margin" value={now?.margin} previous={before?.margin} />
    </section>
  );
}

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "short" });

function monthLabel(iso: string): string {
  return MONTH.format(new Date(`${iso}T00:00:00`));
}

/** Bar heights only; amounts are shown from the API's strings, never from this. */
function share(amount: string, max: bigint): number {
  const paise = toPaise(amount) ?? 0n;
  if (max <= 0n || paise <= 0n) return 0;
  return Number((paise * 1000n) / max) / 1000;
}

function MonthsChart({ months }: { months: Month[] }) {
  const max = months.reduce((m, row) => {
    const a = toPaise(row.billed) ?? 0n;
    const b = toPaise(row.collected) ?? 0n;
    const big = a > b ? a : b;
    return big > m ? big : m;
  }, 0n);
  const h = 120;
  const slot = 40;
  return (
    <figure className="grid gap-2">
      <svg
        viewBox={`0 0 ${months.length * slot} ${h + 18}`}
        className="h-44 w-full"
        role="img"
        aria-label="Billed and collected, last 12 months"
      >
        {months.map((m, i) => {
          const billed = share(m.billed, max) * h;
          const collected = share(m.collected, max) * h;
          const x = i * slot + 6;
          return (
            <g key={m.month}>
              <rect x={x} y={h - billed} width={13} height={billed} className="fill-primary" rx={2}>
                <title>{`${monthLabel(m.month)}: billed ${formatInr(m.billed)}`}</title>
              </rect>
              <rect
                x={x + 15}
                y={h - collected}
                width={13}
                height={collected}
                className="fill-chart-2"
                rx={2}
              >
                <title>{`${monthLabel(m.month)}: collected ${formatInr(m.collected)}`}</title>
              </rect>
              <text
                x={x + 14}
                y={h + 14}
                textAnchor="middle"
                className="fill-muted-foreground text-[10px]"
              >
                {monthLabel(m.month)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="text-muted-foreground flex gap-4 text-xs">
        <span className="flex items-center gap-1">
          <span className="bg-primary inline-block size-2 rounded-sm" aria-hidden /> Billed
        </span>
        <span className="flex items-center gap-1">
          <span className="bg-chart-2 inline-block size-2 rounded-sm" aria-hidden /> Collected
        </span>
      </figcaption>
      <details className="text-sm">
        <summary className="text-muted-foreground cursor-pointer text-xs">Show as a table</summary>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Month</TableHead>
              <TableHead className="text-right">Billed</TableHead>
              <TableHead className="text-right">Collected</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {months.map((m) => (
              <TableRow key={m.month}>
                <TableCell>{m.month.slice(0, 7)}</TableCell>
                <Amount value={m.billed} />
                <Amount value={m.collected} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </details>
    </figure>
  );
}

function OverdueBill({ row }: { row: OverdueRow }) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/reminders", {
          params: { path: { document_id: row.document_id } },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["reports", "dashboard"] }),
  });
  const last = row.last_reminder_at ? formatDayMonth(row.last_reminder_at) : null;
  return (
    <TableRow>
      <TableCell>
        <Link to={`/documents/${row.document_id}`} className="font-medium hover:underline">
          {row.doc_number}
        </Link>
        <div className="text-muted-foreground text-xs">
          {DOC_TYPE_LABELS[row.doc_type as DocType]} · {row.party_name}
        </div>
      </TableCell>
      <TableCell className="text-destructive tabular-nums">{row.days_overdue} days</TableCell>
      <Amount value={row.outstanding} strong />
      <TableCell className="text-right">
        {send.isSuccess ? (
          <span className="text-muted-foreground text-xs">Reminder sent</span>
        ) : (
          <div className="grid justify-items-end gap-1">
            <Button
              size="sm"
              variant="outline"
              disabled={send.isPending || !row.party_has_email}
              title={row.party_has_email ? undefined : "Add the client's email address first."}
              onClick={() => {
                send.mutate();
              }}
            >
              Send reminder
            </Button>
            {!row.party_has_email && (
              <span className="text-muted-foreground text-xs">No email address</span>
            )}
            {last && <span className="text-muted-foreground text-xs">Last sent {last}</span>}
            {send.isError && (
              <span className="text-destructive text-xs">{errorMessage(send.error)}</span>
            )}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

function Overdue({ data }: { data: Dashboard }) {
  const { count, results } = data.overdue;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Overdue bills</h2>
        </CardTitle>
        <CardDescription>
          {count === 0
            ? "Nothing is past due."
            : count > results.length
              ? `The ${results.length} oldest of ${count} bills past due.`
              : "Bills past their due date, oldest first."}
        </CardDescription>
      </CardHeader>
      {results.length > 0 && (
        <CardContent>
          <Table>
            <TableBody>
              {results.map((row) => (
                <OverdueBill key={row.document_id} row={row} />
              ))}
            </TableBody>
          </Table>
        </CardContent>
      )}
    </Card>
  );
}

function LosingProjects({ data }: { data: Dashboard }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Projects losing money</h2>
        </CardTitle>
        <CardDescription>Costs so far are more than what has been billed.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.losing_projects.length === 0 ? (
          <p className="text-muted-foreground text-sm">None. Every project is billed above cost.</p>
        ) : (
          <ul className="grid gap-2">
            {data.losing_projects.map((p) => (
              <li key={p.project_id} className="flex justify-between gap-2 text-sm">
                <Link to={`/projects/${p.project_id}`} className="hover:underline">
                  {p.name} <span className="text-muted-foreground">{p.code}</span>
                </Link>
                <span className="text-destructive tabular-nums">{formatInr(p.margin)}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Drafts({ data }: { data: Dashboard }) {
  const { count, results } = data.drafts;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Drafts waiting to be issued</h2>
        </CardTitle>
        <CardDescription>
          {count === 0
            ? "No drafts."
            : `${count} ${count === 1 ? "draft" : "drafts"}, oldest first.`}
        </CardDescription>
      </CardHeader>
      {results.length > 0 && (
        <CardContent>
          <ul className="grid gap-2">
            {results.map((d) => (
              <li key={d.id} className="flex justify-between gap-2 text-sm">
                <Link to={`/documents/${d.id}/edit`} className="hover:underline">
                  {DOC_TYPE_LABELS[d.doc_type as DocType]} · {d.party_name}
                </Link>
                <span className="tabular-nums">{formatInr(d.grand_total)}</span>
              </li>
            ))}
          </ul>
          {count > results.length && (
            <Link to="/documents" className="text-muted-foreground mt-2 block text-xs underline">
              All documents
            </Link>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function Receivables({ book }: { book: Book }) {
  const receivables = useQuery({
    queryKey: ["reports", "receivables", { book }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/receivables", { params: { query: { book } } })),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Receivables by party</h2>
        </CardTitle>
        <CardDescription>What each client owes today, by how long it is past due.</CardDescription>
      </CardHeader>
      <CardContent>
        {receivables.error ? (
          <ErrorState error={receivables.error} />
        ) : !receivables.data ? (
          <Skeleton className="h-24 w-full" />
        ) : receivables.data.results.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nothing outstanding.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Party</TableHead>
                {BUCKETS.map((b) => (
                  <TableHead key={b.key} className="text-right">
                    {b.label}
                  </TableHead>
                ))}
                <TableHead className="text-right">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {receivables.data.results.map((row) => (
                <TableRow key={row.party_id}>
                  <TableCell>
                    <Link to={`/parties/${row.party_id}`} className="font-medium hover:underline">
                      {row.display_name}
                    </Link>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {row.document_count} {row.document_count === 1 ? "bill" : "bills"}
                    </span>
                  </TableCell>
                  {BUCKETS.map((b) => (
                    <Amount
                      key={b.key}
                      value={String(row[b.key])}
                      late={b.key === "days_90_plus"}
                    />
                  ))}
                  <Amount value={row.total} strong />
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell>All parties</TableCell>
                {BUCKETS.map((b) => (
                  <Amount key={b.key} value={String(receivables.data.totals[b.key])} />
                ))}
                <Amount value={receivables.data.totals.total} strong />
              </TableRow>
            </TableFooter>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function Amount({ value, strong, late }: { value: string; strong?: boolean; late?: boolean }) {
  const zero = /^0+(\.0+)?$/.test(value);
  return (
    <TableCell
      className={cn(
        "text-right tabular-nums",
        zero && "text-muted-foreground",
        strong && "font-medium",
        late && !zero && "text-destructive",
      )}
    >
      {zero ? "–" : formatInr(value)}
    </TableCell>
  );
}

function Main({ from, to, book }: { from: string; to: string; book: Book }) {
  const dashboard = useQuery({
    queryKey: ["reports", "dashboard", { from, to, book }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/dashboard", { params: { query: { from, to, book } } })),
  });
  if (dashboard.error) {
    return <ErrorState error={dashboard.error} title="Could not load the dashboard" />;
  }
  const data = dashboard.data;
  return (
    <div className="grid gap-6">
      <Summary data={data} />
      {data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Billed and collected</h2>
              </CardTitle>
              <CardDescription>The last 12 months.</CardDescription>
            </CardHeader>
            <CardContent>
              <MonthsChart months={data.months} />
            </CardContent>
          </Card>
          <Overdue data={data} />
          <div className="grid gap-6 lg:grid-cols-2">
            <LosingProjects data={data} />
            <Drafts data={data} />
          </div>
        </>
      ) : (
        <Skeleton className="h-64 w-full" />
      )}
      <Receivables book={book} />
    </div>
  );
}

export function DashboardPage() {
  const [period, setPeriod] = useState<PeriodKey>("this_fy");
  const [book, setBook] = useState<Book>("ALL");
  const { from, to } = periodRange(period, new Date());
  return (
    <>
      <Welcome />
      <PageHeader
        title="Dashboard"
        description={formatRange(from, to)}
        actions={
          <>
            <NativeSelect
              aria-label="Period"
              value={period}
              onChange={(e) => {
                setPeriod(e.target.value as PeriodKey);
              }}
              className="w-auto"
            >
              {Object.entries(PERIOD_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="Book"
              value={book}
              onChange={(e) => {
                setBook(e.target.value as Book);
              }}
              className="w-auto"
            >
              {BOOKS.map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
            </NativeSelect>
          </>
        }
      />
      <Main from={from} to={to} book={book} />
    </>
  );
}
