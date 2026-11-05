import type { ComponentProps } from "react";

import { TableCell } from "@/components/ui/table";
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

/**
 * An amount as it is shown everywhere (D.3): from the API's string, formatted
 * with Indian grouping by `formatInr` (never parseFloat / Number), tabular
 * figures so columns line up. `muted` greys a zero, `strong` is for totals.
 */
export function Money({
  value,
  strong = false,
  muted = false,
  className,
}: {
  value: string | null | undefined;
  strong?: boolean;
  muted?: boolean;
  className?: string;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className={cn("text-muted-foreground", className)}>–</span>;
  }
  return (
    <span
      className={cn(
        "whitespace-nowrap tabular-nums",
        strong && "font-semibold",
        muted && "text-muted-foreground",
        className,
      )}
    >
      {formatInr(value)}
    </span>
  );
}

/** A table cell holding an amount: right-aligned, like every amount column. */
export function MoneyCell({
  value,
  strong,
  muted,
  className,
  ...props
}: Omit<ComponentProps<typeof TableCell>, "children"> & {
  value: string | null | undefined;
  strong?: boolean;
  muted?: boolean;
}) {
  return (
    <TableCell className={cn("text-right", className)} {...props}>
      <Money value={value} strong={strong} muted={muted} />
    </TableCell>
  );
}
