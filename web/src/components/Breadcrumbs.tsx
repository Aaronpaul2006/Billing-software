import { ArrowLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router";

import { useMediaQuery } from "@/lib/useMediaQuery";

export interface Crumb {
  label: string;
  /** Leave out for the page you are on (the last crumb). */
  to?: string;
}

/**
 * Where a detail page sits (D.5): "Bills › INV/0002". On phones only the way
 * back is shown ("← Bills"), to save the space.
 */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  const wide = useMediaQuery("(min-width: 640px)");
  const parent = [...items].reverse().find((c) => c.to);
  if (!wide) {
    return parent?.to ? (
      <nav aria-label="Breadcrumb" className="mb-2">
        <Link
          to={parent.to}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ArrowLeft className="size-4" aria-hidden /> {parent.label}
        </Link>
      </nav>
    ) : null;
  }
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="text-muted-foreground flex flex-wrap items-center gap-1 text-sm">
        {items.map((c, i) => (
          <li key={`${c.label}-${String(i)}`} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="size-3.5 opacity-60" aria-hidden />}
            {c.to ? (
              <Link to={c.to} className="hover:text-foreground hover:underline">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="text-foreground font-medium">
                {c.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
