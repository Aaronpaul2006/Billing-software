import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { fyStartYear, isoDate, periodRange } from "@/features/dashboard/periods";
import { compareMoney, formatInr, formatQty, toPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

type TdsStatus = components["schemas"]["TdsRowStatusEnum"];

const TABS = [
  { key: "gst", label: "GST summary" },
  { key: "projects", label: "Project margins" },
  { key: "tds", label: "TDS reconciliation" },
  { key: "months", label: "Billing by month" },
] as const;

function Money({ value, className }: { value: string | null; className?: string }) {
  return (
    <TableCell className={cn("text-right tabular-nums", className)}>
      {value === null ? "–" : formatInr(value)}
    </TableCell>
  );
}

function GstSummary() {
  const [period, setPeriod] = useState(() => isoDate(new Date()).slice(0, 7));
  const report = useQuery({
    queryKey: ["reports", "gst", period],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/gst-summary", { params: { query: { period } } })),
    enabled: /^\d{4}-\d{2}$/.test(period),
  });
  return (
    <div className="grid gap-4">
      <div className="grid max-w-48 gap-2">
        <Label htmlFor="gst-period">Month</Label>
        <Input
          id="gst-period"
          type="month"
          value={period}
          onChange={(e) => {
            setPeriod(e.target.value);
          }}
        />
      </div>
      <p className="text-muted-foreground text-sm">
        Outward supplies on issued GST documents, by B2B (client has a GSTIN) / B2C and rate; credit
        notes count negative. The basis for GSTR-1 and GSTR-3B.
      </p>
      {report.error ? (
        <ErrorState error={report.error} />
      ) : !report.data ? (
        <Skeleton className="h-24 w-full" />
      ) : report.data.results.length === 0 ? (
        <p className="text-muted-foreground text-sm">No GST documents in this month.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Supply</TableHead>
              <TableHead className="text-right">Rate</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead className="text-right">Taxable value</TableHead>
              <TableHead className="text-right">CGST</TableHead>
              <TableHead className="text-right">SGST</TableHead>
              <TableHead className="text-right">IGST</TableHead>
              <TableHead className="text-right">Cess</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.data.results.map((r) => (
              <TableRow key={`${r.supply}-${r.gst_rate}`}>
                <TableCell>{r.supply}</TableCell>
                <TableCell className="text-right">{formatQty(r.gst_rate)} %</TableCell>
                <TableCell className="text-right">{r.document_count}</TableCell>
                <Money value={r.taxable_value} />
                <Money value={r.cgst} />
                <Money value={r.sgst} />
                <Money value={r.igst} />
                <Money value={r.cess} />
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={3}>Total</TableCell>
              <Money value={report.data.totals.taxable_value} />
              <Money value={report.data.totals.cgst} />
              <Money value={report.data.totals.sgst} />
              <Money value={report.data.totals.igst} />
              <Money value={report.data.totals.cess} />
            </TableRow>
          </TableFooter>
        </Table>
      )}
    </div>
  );
}

function ProjectMargins() {
  const report = useQuery({
    queryKey: ["reports", "projects"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/projects")),
  });
  if (report.error) return <ErrorState error={report.error} />;
  if (!report.data) return <Skeleton className="h-24 w-full" />;
  if (report.data.results.length === 0)
    return <p className="text-muted-foreground text-sm">No projects.</p>;
  return (
    <div className="grid gap-4">
      <p className="text-muted-foreground text-sm">
        Margin = taxable value billed − cost (expenses; GST counts as cost unless it can be claimed
        back).
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Project</TableHead>
            <TableHead className="text-right">Contract</TableHead>
            <TableHead className="text-right">Billed</TableHead>
            <TableHead className="text-right">Cost</TableHead>
            <TableHead className="text-right">Margin</TableHead>
            <TableHead className="text-right">Retention held</TableHead>
            <TableHead className="text-right">Outstanding</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {report.data.results.map((r) => (
            <TableRow key={r.project_id}>
              <TableCell>
                <Link to={`/projects/${r.project_id}`} className="font-medium hover:underline">
                  {r.name}
                </Link>
                <div className="text-muted-foreground font-mono text-xs">{r.code}</div>
              </TableCell>
              <Money value={r.contract_value} />
              <Money value={r.billed_taxable} />
              <Money value={r.cost} />
              <Money
                value={r.margin}
                className={cn(
                  "font-medium",
                  compareMoney(r.margin, "0") === -1 && "text-destructive",
                )}
              />
              <Money value={r.retention_held} />
              <Money value={r.outstanding} />
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const TDS_STATUS: Record<
  TdsStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  MATCHED: { label: "Matched", variant: "default" },
  SHORT: { label: "Short", variant: "destructive" },
  EXCESS: { label: "Excess", variant: "outline" },
  NOT_RECEIVED: { label: "Not received", variant: "secondary" },
};

function TdsReconciliation() {
  const current = fyStartYear(new Date());
  const [fy, setFy] = useState(current);
  const report = useQuery({
    queryKey: ["reports", "tds", fy],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/tds-reconciliation", { params: { query: { fy } } })),
  });
  return (
    <div className="grid gap-4">
      <div className="grid max-w-48 gap-2">
        <Label htmlFor="tds-fy">Financial year</Label>
        <NativeSelect
          id="tds-fy"
          value={fy}
          onChange={(e) => {
            setFy(Number(e.target.value));
          }}
        >
          {[current, current - 1, current - 2].map((y) => (
            <option key={y} value={y}>
              {y}–{String(y + 1).slice(2)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <p className="text-muted-foreground text-sm">
        Income-tax TDS (s.194C) on your issued bills, by bill date, against the Form 16A
        certificates recorded. Overdue: the certificate was due 15 days after the client&apos;s
        quarterly return.
      </p>
      {report.error ? (
        <ErrorState error={report.error} />
      ) : !report.data ? (
        <Skeleton className="h-24 w-full" />
      ) : report.data.results.length === 0 ? (
        <p className="text-muted-foreground text-sm">No TDS on bills or certificates this year.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Client</TableHead>
              <TableHead>Quarter</TableHead>
              <TableHead className="text-right">On our bills</TableHead>
              <TableHead className="text-right">Certified</TableHead>
              <TableHead className="text-right">Difference</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.data.results.map((r) => (
              <TableRow key={`${r.party_id}-${String(r.quarter)}`}>
                <TableCell>
                  {r.display_name}
                  {r.deductor_tans && (
                    <div className="text-muted-foreground font-mono text-xs">{r.deductor_tans}</div>
                  )}
                </TableCell>
                <TableCell>Q{r.quarter}</TableCell>
                <Money value={r.expected} />
                <Money value={r.certified} />
                <Money
                  value={r.difference}
                  className={cn(compareMoney(r.difference, "0") === -1 && "text-destructive")}
                />
                <TableCell>
                  <Badge variant={TDS_STATUS[r.status].variant}>{TDS_STATUS[r.status].label}</Badge>
                  {r.overdue && (
                    <span className="text-destructive ml-2 text-xs">
                      overdue since {r.certificate_due}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={2}>Total</TableCell>
              <Money value={report.data.totals.expected} />
              <Money value={report.data.totals.certified} />
              <Money value={report.data.totals.difference} />
              <TableCell />
            </TableRow>
          </TableFooter>
        </Table>
      )}
    </div>
  );
}

function BillingByMonth() {
  const { from, to } = periodRange("this_fy", new Date());
  const report = useQuery({
    queryKey: ["reports", "months", from, to],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reports/billing-by-month", { params: { query: { from, to } } }),
      ),
  });
  if (report.error) return <ErrorState error={report.error} />;
  if (!report.data) return <Skeleton className="h-24 w-full" />;
  const rows = report.data.results;
  if (rows.length === 0)
    return <p className="text-muted-foreground text-sm">Nothing billed this financial year.</p>;
  // Bar widths only: the ratio of paise as BigInt, so no amount ever becomes a float.
  const largest = rows.reduce((m, r) => {
    const p = toPaise(r.billed) ?? 0n;
    return p > m ? p : m;
  }, 1n);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Month</TableHead>
          <TableHead>Book</TableHead>
          <TableHead className="text-right">Documents</TableHead>
          <TableHead className="text-right">Billed</TableHead>
          <TableHead className="w-1/3">
            <span className="sr-only">Bar</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const p = toPaise(r.billed) ?? 0n;
          const pct = p > 0n ? Number((p * 100n) / largest) : 0;
          return (
            <TableRow key={`${r.month}-${r.book}`}>
              <TableCell>
                {new Date(`${r.month}T00:00:00`).toLocaleDateString("en-IN", {
                  month: "short",
                  year: "numeric",
                })}
              </TableCell>
              <TableCell>{r.book === "GST" ? "GST" : "Non-GST"}</TableCell>
              <TableCell className="text-right">{r.document_count}</TableCell>
              <Money value={r.billed} />
              <TableCell>
                <div
                  className="bg-primary h-2 rounded-full"
                  style={{ width: `${String(pct)}%` }}
                  aria-hidden
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((t) => t.key === params.get("tab"))?.key ?? "gst";
  return (
    <>
      <PageHeader title="Reports" />
      <nav aria-label="Reports" className="mb-6 flex flex-wrap gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-current={tab === t.key ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === t.key
                ? "border-primary font-medium"
                : "text-muted-foreground hover:text-foreground border-transparent",
            )}
            onClick={() => {
              setParams({ tab: t.key });
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "gst" && <GstSummary />}
      {tab === "projects" && <ProjectMargins />}
      {tab === "tds" && <TdsReconciliation />}
      {tab === "months" && <BillingByMonth />}
    </>
  );
}
