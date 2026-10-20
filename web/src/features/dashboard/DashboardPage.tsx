import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

import { formatRange, PERIOD_LABELS, periodRange } from "./periods";
import type { PeriodKey } from "./periods";

type Book = "ALL" | "GST" | "NON_GST";
type Totals = components["schemas"]["ReportTotals"];
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

function Summary({ from, to, book }: { from: string; to: string; book: Book }) {
  const summary = useQuery({
    queryKey: ["reports", "summary", { from, to, book }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/summary", { params: { query: { from, to, book } } })),
  });
  if (summary.error) return <ErrorState error={summary.error} title="Could not load the summary" />;
  const current: Totals | undefined = summary.data?.current;
  const previous: Totals | undefined = summary.data?.previous;
  return (
    <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard title="Billed" value={current?.billed} previous={previous?.billed} />
      <StatCard title="Collected" value={current?.collected} previous={previous?.collected} />
      <StatCard title="Outstanding" value={current?.outstanding} note="Owed to you today" />
      <StatCard title="Expenses" value={current?.expenses} previous={previous?.expenses} />
    </section>
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

export function DashboardPage() {
  const [period, setPeriod] = useState<PeriodKey>("this_fy");
  const [book, setBook] = useState<Book>("ALL");
  const { from, to } = periodRange(period, new Date());
  return (
    <>
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
      <div className="grid gap-6">
        <Summary from={from} to={to} book={book} />
        <Receivables book={book} />
      </div>
    </>
  );
}
