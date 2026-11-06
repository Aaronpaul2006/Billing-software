import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { formatDate, formatDayMonth } from "@/lib/dates";
import { compareMoney } from "@/lib/money";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

type Forecast = components["schemas"]["CashFlow"];
type Week = components["schemas"]["CashFlowWeek"];
type Item = components["schemas"]["CashFlowItem"];

const WEEKS = ["4", "8", "13"] as const;

function below(amount: string): boolean {
  return compareMoney(amount, "0.00") === -1;
}

function weekLabel(w: Week): string {
  return `${formatDayMonth(w.start)} – ${formatDayMonth(w.end)}`;
}

/** The low–high range; red when it may go below zero. */
function Range({ low, high }: { low: string; high: string }) {
  if (low === high) return <Money value={low} className={cn(below(low) && "text-destructive")} />;
  return (
    <span className="whitespace-nowrap">
      <Money value={low} className={cn(below(low) && "text-destructive")} />
      <span className="text-muted-foreground"> to </span>
      <Money value={high} className={cn(below(high) && "text-destructive")} />
    </span>
  );
}

function BillLink({ item }: { item: Item }) {
  if (item.kind === "RETENTION_RELEASE")
    return <span className="font-medium">Retention release {item.number}</span>;
  const to = item.kind === "VENDOR_BILL" ? `/vendor-bills/${item.id}` : `/documents/${item.id}`;
  return (
    <Link to={to} className="font-medium hover:underline">
      {item.number || "Bill"}
    </Link>
  );
}

function BillList({ title, items, empty }: { title: string; items: Item[]; empty: string }) {
  return (
    <section aria-label={title} className="mt-6">
      <h3 className="text-sm font-semibold">{title}</h3>
      {items.length === 0 ? (
        <p className="text-muted-foreground mt-2 text-sm">{empty}</p>
      ) : (
        <ul className="divide-border mt-2 divide-y">
          {items.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-4 py-2 text-sm">
              <div className="min-w-0">
                <BillLink item={item} />
                <div className="text-help text-muted-foreground truncate">
                  {item.party_name} · due {formatDate(item.due_date)}
                </div>
              </div>
              <Money value={item.outstanding} className="text-figure shrink-0" />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Summary({ forecast }: { forecast: Forecast }) {
  const { role } = useSession();
  const lowest = forecast.weeks.find((w) => w.start === forecast.lowest_week_start);
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle>
          <h2>The next {forecast.weeks.length} weeks</h2>
        </CardTitle>
        <CardDescription>
          From the bills already made: what clients owe by due date, and what we owe vendors.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 @2xl:grid-cols-2 @5xl:grid-cols-4">
        <div>
          <p className="text-muted-foreground text-sm">Cash now</p>
          {forecast.cash_today === null ? (
            <p className="text-sm">
              No bank statement yet, so the balances show the change only.{" "}
              {can(role, "payments.record") && (
                <Link
                  to="/bank"
                  className="text-primary inline-flex min-h-8 items-center font-medium hover:underline"
                >
                  Import a statement
                </Link>
              )}
            </p>
          ) : (
            <>
              <p className="text-figure font-semibold">
                <Money value={forecast.cash_today} />
              </p>
              <p className="text-help text-muted-foreground">{forecast.cash_sources.join("; ")}</p>
            </>
          )}
        </div>
        <div>
          <p className="text-muted-foreground text-sm">
            {forecast.cash_today === null ? "Lowest point, from today" : "Lowest expected balance"}
          </p>
          <p
            className={cn(
              "text-figure font-semibold",
              below(forecast.lowest_balance) && "text-destructive",
            )}
          >
            <Money value={forecast.lowest_balance} />
          </p>
          {lowest && <p className="text-help text-muted-foreground">Week of {weekLabel(lowest)}</p>}
        </div>
        <div>
          <p className="text-muted-foreground text-sm">Overdue from clients</p>
          <p className="text-figure font-semibold">
            <Money value={forecast.overdue_in} />
          </p>
          <p className="text-help text-muted-foreground">Not counted on in the low balance</p>
        </div>
        <div>
          <p className="text-muted-foreground text-sm">Overdue to vendors</p>
          <p className="text-figure font-semibold">
            <Money value={forecast.overdue_out} />
          </p>
          <p className="text-help text-muted-foreground">Taken as paid this week</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function CashFlowPage() {
  const [weeks, setWeeks] = useState<(typeof WEEKS)[number]>("8");
  const [open, setOpen] = useState<Week | null>(null);
  const forecast = useQuery({
    queryKey: ["reports", "cash-flow", weeks],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reports/cash-flow", {
          params: { query: { weeks: Number(weeks) } },
        }),
      ),
  });

  const columns: Column<Week>[] = [
    {
      id: "week",
      header: "Week",
      card: "title",
      cell: (w) => <span className="font-medium whitespace-nowrap">{weekLabel(w)}</span>,
    },
    {
      id: "flow",
      header: "In and out",
      cardOnly: true,
      card: "subtitle",
      cell: (w) => (
        <span className="text-muted-foreground">
          In <Money value={w.money_in} /> · Out <Money value={w.money_out} />
        </span>
      ),
    },
    {
      id: "in",
      header: "Money in",
      align: "right",
      card: "hidden",
      cell: (w) => <Money value={w.money_in} muted={w.money_in === "0.00"} />,
    },
    {
      id: "out",
      header: "Money out",
      align: "right",
      card: "hidden",
      cell: (w) => <Money value={w.money_out} muted={w.money_out === "0.00"} />,
    },
    {
      id: "balance",
      header: "Expected balance",
      align: "right",
      card: "amount",
      cell: (w) => <Range low={w.balance_low} high={w.balance_high} />,
    },
    {
      id: "bills",
      header: "Bills",
      align: "right",
      card: "detail",
      cell: (w) => {
        const n = w.bills_in.length + w.bills_out.length;
        return n === 0 ? (
          <span className="text-muted-foreground text-sm">None</span>
        ) : (
          <Button
            variant="outline"
            size="sm"
            aria-label={`${String(n)} ${n === 1 ? "bill" : "bills"}, ${weekLabel(w)}`}
            onClick={() => {
              setOpen(w);
            }}
          >
            {n} {n === 1 ? "bill" : "bills"}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="@container">
      <PageHeader
        title="Cash flow"
        description="Money due in and out, week by week, and the balance to expect."
        actions={
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Show</span>
            <NativeSelect
              value={weeks}
              aria-label="Weeks to show"
              onChange={(e) => {
                setWeeks(e.target.value as (typeof WEEKS)[number]);
              }}
            >
              {WEEKS.map((n) => (
                <option key={n} value={n}>
                  {n} weeks
                </option>
              ))}
            </NativeSelect>
          </label>
        }
      />
      {forecast.isError ? (
        <ErrorState error={forecast.error} />
      ) : (
        <>
          {forecast.data && <Summary forecast={forecast.data} />}
          <DataTable
            label="Cash flow by week"
            rows={forecast.data?.weeks ?? []}
            columns={columns}
            rowKey={(w) => w.start}
            rowLabel={weekLabel}
            loading={forecast.isPending}
          />
          <p className="text-help text-muted-foreground mt-3">
            The balance is a range: the low figure assumes overdue client bills do not come in
            during these weeks; the high one, that they come in now.
          </p>
        </>
      )}
      <Sheet
        open={open !== null}
        onOpenChange={(o) => {
          if (!o) setOpen(null);
        }}
      >
        <SheetContent
          side="right"
          closeLabel="Close"
          className="w-full max-w-lg overflow-y-auto p-4 pt-12 sm:w-[32rem] sm:max-w-lg"
        >
          <SheetTitle className="text-section">
            {open ? `Week of ${weekLabel(open)}` : "Week"}
          </SheetTitle>
          <SheetDescription className="text-muted-foreground text-sm">
            The bills falling due this week that are still owed.
          </SheetDescription>
          {open && (
            <>
              <BillList
                title="Coming in"
                items={open.bills_in}
                empty="Nothing from clients falls due."
              />
              <BillList
                title="Going out"
                items={open.bills_out}
                empty="No vendor bills fall due."
              />
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
