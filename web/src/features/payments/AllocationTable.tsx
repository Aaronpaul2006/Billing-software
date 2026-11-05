import { Link } from "react-router";

import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  compareMoney,
  fillInOrder,
  formatInr,
  subtractMoney,
  sumMoney,
  toPaise,
} from "@/lib/money";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/dates";

import type { Allocations, OpenItem } from "./allocations";

/**
 * The party's open invoices (and retention releases) with an amount to
 * allocate on each. "Fill oldest first" spreads what is available.
 */
export function AllocationTable({
  items,
  allocations,
  onChange,
  available,
  isLoading,
  error,
}: {
  items: readonly OpenItem[];
  allocations: Allocations;
  onChange: (next: Allocations) => void;
  available: string;
  isLoading: boolean;
  error: unknown;
}) {
  if (error) return <ErrorState error={error} />;
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (items.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        Nothing is owed: the payment stays unallocated (an advance).
      </p>
    );
  }
  const total = sumMoney(Object.values(allocations)) ?? "0.00";
  const left = subtractMoney(available || "0", total);
  const over = left !== null && compareMoney(left, "0") === -1;
  return (
    <div className="grid gap-2">
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!available || (toPaise(available) ?? 0n) <= 0n}
          onClick={() => {
            const filled = fillInOrder(
              available,
              items.map((i) => i.outstanding),
            );
            onChange(Object.fromEntries(items.map((i, n) => [i.key, filled[n] ?? ""])));
          }}
        >
          Fill oldest first
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Owed</TableHead>
            <TableHead>Date</TableHead>
            <TableHead className="text-right">Outstanding</TableHead>
            <TableHead className="w-40 text-right">Allocate</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.key}>
              <TableCell>
                {item.href ? (
                  <Link to={item.href} className="font-medium hover:underline">
                    {item.label}
                  </Link>
                ) : (
                  <span className="font-medium">{item.label}</span>
                )}
                <div className="text-muted-foreground text-xs">{item.detail}</div>
              </TableCell>
              <TableCell>{formatDate(item.date)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatInr(item.outstanding)}
              </TableCell>
              <TableCell className="text-right">
                <Input
                  aria-label={`Allocate to ${item.label}`}
                  inputMode="decimal"
                  className="text-right"
                  value={allocations[item.key] ?? ""}
                  onChange={(e) => {
                    onChange({ ...allocations, [item.key]: e.target.value });
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell colSpan={3}>Allocated</TableCell>
            <TableCell className="text-right tabular-nums">{formatInr(total)}</TableCell>
          </TableRow>
          <TableRow>
            <TableCell colSpan={3}>Left unallocated</TableCell>
            <TableCell className={cn("text-right tabular-nums", over && "text-destructive")}>
              {left === null ? "–" : formatInr(left)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </div>
  );
}
