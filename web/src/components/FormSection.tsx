import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A titled group of fields in a form (D.3): the title and a line of
 * explanation on the left on wide screens, the fields beside them; stacked on
 * phones. Fields sit in two columns from small tablets up.
 */
export function FormSection({
  title,
  description,
  children,
  columns = 2,
  className,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  columns?: 1 | 2;
  className?: string;
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "bg-card grid gap-4 rounded-xl border p-4 shadow-xs sm:p-6 lg:grid-cols-[14rem_1fr] lg:gap-8",
        className,
      )}
    >
      <div className="grid content-start gap-1">
        <h2 className="text-section font-semibold">{title}</h2>
        {description && <p className="text-help text-muted-foreground">{description}</p>}
      </div>
      <div className={cn("grid content-start gap-4", columns === 2 && "sm:grid-cols-2")}>
        {children}
      </div>
    </section>
  );
}
