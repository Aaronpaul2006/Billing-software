import type { ReactNode } from "react";

import { STATUS_TEXT } from "@/components/status";
import type { Status } from "@/components/status";
import { cn } from "@/lib/utils";

const STYLE: Record<Status, string> = {
  draft: "bg-muted text-muted-foreground border-border border-dashed",
  issued: "bg-info-soft text-info border-info-border",
  part_paid: "bg-warning-soft text-warning border-warning-border",
  paid: "bg-success-soft text-success border-success-border",
  overdue: "bg-destructive-soft text-destructive border-destructive-border",
  accepted: "bg-success-soft text-success border-success-border",
  declined: "bg-muted text-muted-foreground border-border",
  cancelled: "bg-muted text-muted-foreground border-border line-through decoration-1",
  voided: "bg-muted text-muted-foreground border-border line-through decoration-1",
  planned: "bg-muted text-muted-foreground border-border border-dashed",
  active: "bg-info-soft text-info border-info-border",
  on_hold: "bg-warning-soft text-warning border-warning-border",
  completed: "bg-success-soft text-success border-success-border",
};

export function StatusBadge({
  status,
  children,
  className,
}: {
  status: Status;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        STYLE[status],
        className,
      )}
    >
      {children ?? STATUS_TEXT[status]}
    </span>
  );
}
