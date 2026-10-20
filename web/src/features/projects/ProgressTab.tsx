import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { formatInr, formatQty } from "@/lib/money";
import { cn } from "@/lib/utils";

import { useProjectOutlet } from "./api";

/** A bar for a percentage the server computed ("42.50"); display only. */
function ProgressBar({ pct }: { pct: string | null }) {
  if (pct === null) return <span className="text-muted-foreground">–</span>;
  const width = Math.min(Number(pct), 100);
  return (
    <div className="flex items-center gap-2">
      <div className="bg-muted h-2 w-24 overflow-hidden rounded-full" aria-hidden>
        <div
          className={cn("h-full rounded-full", Number(pct) > 100 ? "bg-destructive" : "bg-primary")}
          style={{ width: `${String(width)}%` }}
        />
      </div>
      <span className="tabular-nums">{formatQty(pct)} %</span>
    </div>
  );
}

export function ProgressTab() {
  const { project } = useProjectOutlet();
  const progress = useQuery({
    queryKey: ["boq-progress", project.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/boq-progress", {
          params: { path: { project_id: project.id } },
        }),
      ),
  });

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>BOQ progress</h2>
          </CardTitle>
          <CardDescription>
            Billed in issued tax invoices and bills of supply, against the contract quantities.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {progress.error ? (
            <ErrorState error={progress.error} />
          ) : !progress.data ? (
            <Skeleton className="h-40 w-full" />
          ) : progress.data.results.length === 0 ? (
            <p className="text-muted-foreground text-sm">No BOQ items yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Contract</TableHead>
                  <TableHead className="text-right">Billed</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead className="text-right">Billed value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {progress.data.results.map((r) => (
                  <TableRow key={r.boq_item_id}>
                    <TableCell className="max-w-[24rem] whitespace-normal">
                      <span className="font-mono">{r.item_code}</span> {r.description}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatQty(r.contract_qty)} {r.unit}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatQty(r.billed_qty)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        r.balance_qty.startsWith("-") && "text-destructive",
                      )}
                    >
                      {formatQty(r.balance_qty)}
                    </TableCell>
                    <TableCell>
                      <ProgressBar pct={r.progress_pct} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatInr(r.billed_value)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={4}>
                    Contract {formatInr(progress.data.totals.contract_value)}
                  </TableCell>
                  <TableCell>
                    <ProgressBar pct={progress.data.totals.progress_pct} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInr(progress.data.totals.billed_value)}
                  </TableCell>
                </TableRow>
              </TableFooter>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
