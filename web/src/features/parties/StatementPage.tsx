import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Download } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { PERIOD_LABELS, periodRange } from "@/features/dashboard/periods";
import type { PeriodKey } from "@/features/dashboard/periods";
import { makeAndDownload } from "@/features/exports/exports";
import { errorMessage } from "@/lib/errors";
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

type Entry = components["schemas"]["StatementEntry"];
type FileFormat = "PDF" | "XLSX";

const QUICK: PeriodKey[] = ["this_fy", "last_fy", "this_month", "last_month"];

function day(iso: string): string {
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Where an entry's own page is, if it has one. */
function entryLink(e: Entry): string | null {
  if (e.document_id) return `/documents/${e.document_id}`;
  if (e.payment_id) return `/payments/${e.payment_id}`;
  return null;
}

/** A balance in words: positive = the client owes. */
function side(balance: string): string {
  if (balance.startsWith("-")) return "paid in advance";
  return /^0+(\.0+)?$/.test(balance) ? "settled" : "due from the client";
}

/** A client's statement of account: opening balance, bills and payments, closing balance. */
export function StatementPage() {
  const { partyId = "" } = useParams();
  const [range, setRange] = useState(() => periodRange("this_fy", new Date()));
  const statement = useQuery({
    queryKey: ["statement", partyId, range],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}/statement", {
          params: { path: { party_id: partyId }, query: range },
        }),
      ),
  });
  const [keys, setKeys] = useState<Record<FileFormat, string>>(() => ({
    PDF: newIdempotencyKey(),
    XLSX: newIdempotencyKey(),
  }));
  const download = useMutation({
    mutationFn: async (format: FileFormat) =>
      makeAndDownload(
        { kind: "STATEMENT", format, params: { party_id: partyId, ...range } },
        keys[format],
      ),
    onSuccess: (_, format) => {
      setKeys((k) => ({ ...k, [format]: newIdempotencyKey() }));
    },
  });

  const s = statement.data;
  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to={`/parties/${partyId}`}>
          <ArrowLeft aria-hidden /> {s?.party.display_name ?? "Client"}
        </Link>
      </Button>
      <PageHeader
        title="Statement of account"
        description={
          s
            ? `${s.party.display_name}${s.party.gstin ? ` · GSTIN ${s.party.gstin}` : ""}`
            : undefined
        }
        actions={
          <>
            {(["PDF", "XLSX"] as const).map((f) => (
              <Button
                key={f}
                variant="outline"
                disabled={download.isPending || !s}
                onClick={() => {
                  download.mutate(f);
                }}
              >
                <Download aria-hidden /> {f === "PDF" ? "PDF" : "Excel"}
              </Button>
            ))}
          </>
        }
      />
      <Card className="mb-4 max-w-3xl">
        <CardContent className="grid gap-4 sm:grid-cols-3">
          <Field id="statement-quick" label="Period">
            <NativeSelect
              id="statement-quick"
              defaultValue="this_fy"
              onChange={(e) => {
                setRange(periodRange(e.target.value as PeriodKey, new Date()));
              }}
            >
              {QUICK.map((k) => (
                <option key={k} value={k}>
                  {PERIOD_LABELS[k]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id="statement-from" label="From">
            <Input
              id="statement-from"
              type="date"
              value={range.from}
              onChange={(e) => {
                if (e.target.value) setRange((r) => ({ ...r, from: e.target.value }));
              }}
            />
          </Field>
          <Field id="statement-to" label="To">
            <Input
              id="statement-to"
              type="date"
              value={range.to}
              onChange={(e) => {
                if (e.target.value) setRange((r) => ({ ...r, to: e.target.value }));
              }}
            />
          </Field>
        </CardContent>
      </Card>
      {download.isPending && (
        <p role="status" className="text-muted-foreground mb-4 text-sm">
          Making the file…
        </p>
      )}
      {download.error && (
        <Alert variant="destructive" className="mb-4 max-w-3xl">
          <AlertCircle aria-hidden />
          <AlertDescription>
            {download.error instanceof ApiError || download.error instanceof TypeError
              ? errorMessage(download.error) // the API refused, or no connection
              : download.error.message}
          </AlertDescription>
        </Alert>
      )}
      {statement.error ? (
        <ErrorState error={statement.error} />
      ) : !s ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <>
          <Table aria-label="Statement">
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Particulars</TableHead>
                <TableHead className="text-right">Debit</TableHead>
                <TableHead className="text-right">Credit</TableHead>
                <TableHead className="text-right">Balance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="bg-muted/40 font-medium">
                <TableCell>{day(s.from)}</TableCell>
                <TableCell colSpan={3}>Opening balance</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatInr(s.opening_balance)}
                </TableCell>
              </TableRow>
              {s.entries.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Nothing billed or paid in this period.
                  </TableCell>
                </TableRow>
              )}
              {s.entries.map((e, i) => {
                const link = entryLink(e);
                return (
                  <TableRow key={`${e.date}-${String(i)}`}>
                    <TableCell className="whitespace-nowrap">{day(e.date)}</TableCell>
                    <TableCell className="max-w-[32rem] whitespace-normal">
                      {link ? (
                        <Link to={link} className="hover:underline">
                          {e.description}
                        </Link>
                      ) : (
                        e.description
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {e.debit === "0.00" ? "" : formatInr(e.debit)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {e.credit === "0.00" ? "" : formatInr(e.credit)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        e.balance.startsWith("-") && "text-emerald-700 dark:text-emerald-400",
                      )}
                    >
                      {formatInr(e.balance)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell>{day(s.to)}</TableCell>
                <TableCell>Totals and closing balance</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatInr(s.total_debit)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatInr(s.total_credit)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatInr(s.closing_balance)}
                </TableCell>
              </TableRow>
            </TableFooter>
          </Table>
          <p className="mt-3 text-sm">
            Closing balance <strong>{formatInr(s.closing_balance.replace(/^-/, ""))}</strong>{" "}
            {side(s.closing_balance)}.
          </p>
          <p className="text-muted-foreground mt-1 max-w-3xl text-xs">
            Bills are shown less the retention and TDS deducted on them; retention appears when it
            is released. A mobilisation advance is credited when received and adjusted in the bills
            that recover it.
          </p>
        </>
      )}
    </>
  );
}
