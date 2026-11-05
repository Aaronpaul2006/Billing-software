import type { ReactNode } from "react";

/**
 * The top of every page (D.3): the title, optional badges beside it (status),
 * a line of description, and the page's actions (the main one last).
 */
export function PageHeader({
  title,
  badges,
  description,
  actions,
}: {
  title: string;
  badges?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="grid gap-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-title font-semibold">{title}</h1>
          {badges}
        </div>
        {description && <p className="text-muted-foreground text-sm">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
