import { useEffect, useRef, useState } from "react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * True while the element is wider inside than outside (a table on a phone):
 * the scroll area then takes keyboard focus, so it can be scrolled with the
 * arrow keys (WCAG 2.1.1; axe "scrollable-region-focusable").
 */
function useScrolls<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      setScrolls(el.scrollWidth > el.clientWidth + 1);
    });
    observer.observe(el);
    const table = el.firstElementChild;
    if (table) observer.observe(table);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [ref, scrolls] as const;
}

function Table({ className, ...props }: React.ComponentProps<"table">) {
  const [ref, scrolls] = useScrolls<HTMLDivElement>();
  return (
    <div
      ref={ref}
      data-slot="table-container"
      className="focus-visible:ring-ring/50 relative w-full overflow-x-auto rounded-sm outline-none focus-visible:ring-[3px]"
      {...(scrolls
        ? { tabIndex: 0, role: "region", "aria-label": "Table (scrolls sideways)" }
        : {})}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />
  );
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("bg-muted/50 border-t font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn("hover:bg-muted/50 data-[state=selected]:bg-muted border-b transition-colors", className)}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap",
        className,
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn("p-2 align-middle whitespace-nowrap", className)}
      {...props}
    />
  );
}

export { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow };
