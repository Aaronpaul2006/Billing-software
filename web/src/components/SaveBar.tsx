import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The Save bar of a long form (D.3): stays at the bottom of the screen while
 * the form scrolls, so Save is always one click away. `status` says what is
 * going on ("Unsaved changes", "Saved at 10:42"); `children` are the buttons,
 * the main one last.
 */
export function SaveBar({
  status,
  children,
  className,
}: {
  status?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky bottom-0 z-30 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t px-4 py-3 backdrop-blur md:-mx-6 md:px-6",
        className,
      )}
    >
      {status && (
        <p role="status" className="text-help text-muted-foreground mr-auto">
          {status}
        </p>
      )}
      {children}
    </div>
  );
}
