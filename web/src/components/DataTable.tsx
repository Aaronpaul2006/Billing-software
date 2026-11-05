import { ArrowDown, ArrowUp, ArrowUpDown, MoreHorizontal, Rows3, Rows4 } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { setTableDensity, tableDensity } from "@/lib/appearance";
import type { Density } from "@/lib/appearance";
import { useMediaQuery, WIDE } from "@/lib/useMediaQuery";
import { cn } from "@/lib/utils";

/** Where a column goes when the table becomes cards (screens under 1024 px). */
export type CardSlot = "title" | "subtitle" | "badge" | "amount" | "detail" | "hidden";

export interface Column<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  /** Sortable by clicking the header (by the server when the table is given `onSortChange`). */
  sortable?: boolean;
  /** For sorting in the browser: amounts as paise (bigint), dates as "YYYY-MM-DD". */
  sortValue?: (row: T) => string | number | bigint | null;
  card?: CardSlot;
  /** Only on the cards (e.g. a summary of several columns), not in the wide table. */
  cardOnly?: boolean;
  className?: string;
}

export interface SortState {
  column: string;
  direction: "asc" | "desc";
}

export interface RowAction {
  label: string;
  onSelect: () => void;
  tone?: "default" | "danger";
  disabled?: boolean;
}

export interface DataTableProps<T> {
  /** The table's name for screen readers, e.g. "Bills". */
  label: string;
  rows: readonly T[];
  columns: readonly Column<T>[];
  rowKey: (row: T) => string;
  /** How a row is named in its actions menu ("More actions for INV/0001"). */
  rowLabel?: (row: T) => string;
  rowActions?: (row: T) => RowAction[];
  loading?: boolean;
  empty?: { title: string; description?: ReactNode; action?: ReactNode };
  /** Server sorting: the current order and a way to change it. Without it, sorting is in the browser. */
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  defaultSort?: SortState;
  /** A last row of totals: column id → content (e.g. a <Money />). */
  totals?: { label: string; cells: Partial<Record<string, ReactNode>> };
  className?: string;
}

function compare(a: string | number | bigint | null, b: string | number | bigint | null): number {
  if (a === b) return 0;
  if (a === null) return 1; // empty values last
  if (b === null) return -1;
  if (typeof a === "string" && typeof b === "string") return a.localeCompare(b, "en-IN");
  return a < b ? -1 : 1;
}

function SortIcon({ direction }: { direction: "asc" | "desc" | null }) {
  if (direction === "asc") return <ArrowUp className="size-3.5" aria-hidden />;
  if (direction === "desc") return <ArrowDown className="size-3.5" aria-hidden />;
  return <ArrowUpDown className="size-3.5 opacity-40" aria-hidden />;
}

function Actions({ actions, rowLabel }: { actions: RowAction[]; rowLabel: string }) {
  if (actions.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={`More actions for ${rowLabel}`}
        >
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {actions.map((a) => (
          <DropdownMenuItem
            key={a.label}
            disabled={a.disabled}
            className={cn(a.tone === "danger" && "text-destructive focus:text-destructive")}
            onSelect={a.onSelect}
          >
            {a.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * The one table of the app (D.4). On wide screens: a table with a header that
 * stays in view, sorting, a row actions menu, a density choice and a totals
 * row. Under 1024 px the same rows become cards (title, status, amount and a
 * few details), so nothing is cut off on phones and tablets.
 */
export function DataTable<T>({
  label,
  rows,
  columns,
  rowKey,
  rowLabel,
  rowActions,
  loading = false,
  empty,
  sort,
  onSortChange,
  defaultSort,
  totals,
  className,
}: DataTableProps<T>) {
  const wide = useMediaQuery(WIDE);
  const [density, setDensity] = useState<Density>(tableDensity);
  const [localSort, setLocalSort] = useState<SortState | null>(defaultSort ?? null);
  const current = onSortChange ? (sort ?? null) : localSort;

  const sorted = useMemo(() => {
    if (onSortChange || !localSort) return rows;
    const col = columns.find((c) => c.id === localSort.column);
    if (!col?.sortValue) return rows;
    const value = col.sortValue;
    const out = [...rows].sort((a, b) => compare(value(a), value(b)));
    return localSort.direction === "desc" ? out.reverse() : out;
  }, [rows, columns, localSort, onSortChange]);

  const toggleSort = (column: string) => {
    const next: SortState =
      current?.column === column && current.direction === "asc"
        ? { column, direction: "desc" }
        : { column, direction: "asc" };
    if (onSortChange) onSortChange(next);
    else setLocalSort(next);
  };

  const tableColumns = columns.filter((c) => !c.cardOnly);
  const nameOf = (row: T) => (rowLabel ? rowLabel(row) : rowKey(row));
  const pad = density === "compact" ? "py-1.5" : "py-3";

  if (!loading && rows.length === 0 && empty) {
    return (
      <div
        className={cn(
          "bg-card grid justify-items-center gap-2 rounded-xl border border-dashed p-8 text-center",
          className,
        )}
      >
        <p className="text-section font-semibold">{empty.title}</p>
        {empty.description && (
          <p className="text-help text-muted-foreground max-w-prose">{empty.description}</p>
        )}
        {empty.action && <div className="mt-2">{empty.action}</div>}
      </div>
    );
  }

  if (!wide) {
    const pick = (slot: CardSlot) => columns.filter((c) => (c.card ?? "detail") === slot);
    return (
      <ul
        aria-label={label}
        aria-busy={loading || undefined}
        className={cn("grid gap-3", className)}
      >
        {loading
          ? Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="bg-card grid gap-2 rounded-xl border p-4">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-3/4" />
              </li>
            ))
          : sorted.map((row) => {
              const actions = rowActions?.(row) ?? [];
              return (
                <li
                  key={rowKey(row)}
                  className="bg-card grid gap-2 rounded-xl border p-4 shadow-xs"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="grid min-w-0 gap-0.5">
                      {pick("title").map((c) => (
                        // links in the title are the card's main tap: at least 24 px tall
                        <div
                          key={c.id}
                          className="font-medium [&_a]:inline-flex [&_a]:min-h-6 [&_a]:items-center"
                        >
                          {c.cell(row)}
                        </div>
                      ))}
                      {pick("subtitle").map((c) => (
                        <div key={c.id} className="text-help text-muted-foreground">
                          {c.cell(row)}
                        </div>
                      ))}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {pick("badge").map((c) => (
                        <div key={c.id}>{c.cell(row)}</div>
                      ))}
                      <Actions actions={actions} rowLabel={nameOf(row)} />
                    </div>
                  </div>
                  {(pick("amount").length > 0 || pick("detail").length > 0) && (
                    <div className="flex justify-between gap-4 text-sm">
                      <dl className="grid content-start gap-1">
                        {pick("detail").map((c) => (
                          <div key={c.id} className="grid">
                            <dt className="text-help text-muted-foreground">{c.header}</dt>
                            <dd>{c.cell(row)}</dd>
                          </div>
                        ))}
                      </dl>
                      <dl className="grid content-start gap-1 text-right">
                        {pick("amount").map((c) => (
                          <div key={c.id} className="grid">
                            <dt className="text-help text-muted-foreground">{c.header}</dt>
                            <dd className="font-medium">{c.cell(row)}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
                </li>
              );
            })}
        {totals && !loading && (
          <li className="bg-muted/60 grid gap-1 rounded-xl border p-4 text-sm">
            <span className="font-semibold">{totals.label}</span>
            {columns
              .filter((c) => totals.cells[c.id] !== undefined)
              .map((c) => (
                <span key={c.id} className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{c.header}</span>
                  <span className="font-semibold">{totals.cells[c.id]}</span>
                </span>
              ))}
          </li>
        )}
      </ul>
    );
  }

  const hasActions = Boolean(rowActions);
  return (
    <div className={cn("grid gap-2", className)}>
      <div className="flex justify-end">
        <Button
          variant="ghost"
          size="sm"
          aria-pressed={density === "compact"}
          onClick={() => {
            const next = density === "compact" ? "comfortable" : "compact";
            setTableDensity(next);
            setDensity(next);
          }}
        >
          {density === "compact" ? <Rows4 aria-hidden /> : <Rows3 aria-hidden />}
          Compact rows
        </Button>
      </div>
      {/* overflow: clip keeps the rounded corners without becoming a scroll box, so the header can stick */}
      <div className="bg-card overflow-clip rounded-xl border shadow-xs">
        <table className="w-full text-sm" aria-busy={loading || undefined}>
          <caption className="sr-only">{label}</caption>
          <thead className="bg-card sticky top-0 z-10 shadow-[0_1px_0_var(--border)]">
            <tr>
              {tableColumns.map((c) => {
                const direction = current?.column === c.id ? current.direction : null;
                return (
                  <th
                    key={c.id}
                    scope="col"
                    aria-sort={
                      direction === "asc"
                        ? "ascending"
                        : direction === "desc"
                          ? "descending"
                          : undefined
                    }
                    className={cn(
                      "text-muted-foreground px-3 py-2.5 text-xs font-medium whitespace-nowrap",
                      c.align === "right" ? "text-right" : "text-left",
                    )}
                  >
                    {c.sortable ? (
                      <button
                        type="button"
                        className={cn(
                          "hover:text-foreground inline-flex items-center gap-1 rounded-sm focus-visible:ring-[3px] focus-visible:outline-none",
                          c.align === "right" && "flex-row-reverse",
                        )}
                        onClick={() => {
                          toggleSort(c.id);
                        }}
                      >
                        {c.header}
                        <SortIcon direction={direction} />
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
              {hasActions && (
                <th scope="col" className="w-10 px-3 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }, (_, i) => (
                  <tr key={i} className="border-t">
                    {tableColumns.map((c) => (
                      <td key={c.id} className={cn("px-3", pad)}>
                        <Skeleton className="h-4 w-full max-w-32" />
                      </td>
                    ))}
                    {hasActions && <td />}
                  </tr>
                ))
              : sorted.map((row) => (
                  <tr key={rowKey(row)} className="hover:bg-muted/40 border-t align-top">
                    {tableColumns.map((c) => (
                      <td
                        key={c.id}
                        className={cn(
                          "px-3",
                          pad,
                          c.align === "right" && "text-right",
                          c.className,
                        )}
                      >
                        {c.cell(row)}
                      </td>
                    ))}
                    {hasActions && (
                      <td
                        className={cn("px-2 text-right", density === "compact" ? "py-0.5" : "py-2")}
                      >
                        <Actions actions={rowActions?.(row) ?? []} rowLabel={nameOf(row)} />
                      </td>
                    )}
                  </tr>
                ))}
          </tbody>
          {totals && !loading && (
            <tfoot>
              <tr className="bg-muted/60 border-t font-semibold">
                {tableColumns.map((c, i) => (
                  <td key={c.id} className={cn("px-3 py-2.5", c.align === "right" && "text-right")}>
                    {i === 0 ? totals.label : totals.cells[c.id]}
                  </td>
                ))}
                {hasActions && <td />}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
