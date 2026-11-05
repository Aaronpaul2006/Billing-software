import { lazy, Suspense, useEffect } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

import { MOD_KEY } from "./keys";

const PaletteBody = lazy(async () => ({ default: (await import("./PaletteBody")).PaletteBody }));

/**
 * Ctrl+K (⌘K on a Mac) anywhere, or the Search button: find a bill, client,
 * project or catalog item, jump to a page, or start something new (D.6).
 */
export function CommandPalette({
  open,
  onOpenChange,
  onHelp,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onHelp: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onOpenChange]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[8vh] max-w-xl translate-y-0 gap-0 overflow-hidden p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">
          Type a bill number, a client, a project or a page; arrow keys move, Enter opens. {MOD_KEY}{" "}
          + K opens this from anywhere.
        </DialogDescription>
        <Suspense fallback={<p className="text-muted-foreground p-4 text-sm">Opening search…</p>}>
          <PaletteBody
            onDone={() => {
              onOpenChange(false);
            }}
            onHelp={onHelp}
          />
        </Suspense>
      </DialogContent>
    </Dialog>
  );
}
