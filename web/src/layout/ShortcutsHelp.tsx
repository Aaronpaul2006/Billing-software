import { useEffect } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { SHORTCUTS as EDITOR } from "@/features/documents/keyboard";

import { MOD_KEY } from "./keys";

const ANYWHERE: { keys: string; what: string }[] = [
  { keys: `${MOD_KEY} + K`, what: "Search, or jump to a page" },
  { keys: "?", what: "Show these shortcuts" },
  { keys: "Esc", what: "Close a menu, dialog or panel" },
  { keys: "Tab / Shift + Tab", what: "Move to the next / previous control" },
];

/** True when a key press is typing into a field (then "?" is just a question mark). */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.closest("input, textarea, select, [contenteditable='true']") !== null
  );
}

function Keys({ rows }: { rows: { keys: string; what: string }[] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
      {rows.map((r) => (
        <div key={r.keys} className="contents">
          <dt>
            <kbd className="bg-muted rounded border px-1.5 py-0.5 font-mono text-xs">{r.keys}</kbd>
          </dt>
          <dd>{r.what}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * "?" anywhere (when not typing) shows the keyboard shortcuts (D.5); the user
 * menu opens it too.
 */
export function ShortcutsHelp({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "?" || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      e.preventDefault();
      onOpenChange(true);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onOpenChange]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogTitle>Keyboard shortcuts</DialogTitle>
        <DialogDescription>Work without the mouse, like in Tally.</DialogDescription>
        <section aria-label="Anywhere" className="grid gap-2">
          <h3 className="text-sm font-semibold">Anywhere</h3>
          <Keys rows={ANYWHERE} />
        </section>
        <section aria-label="On the bill screen" className="grid gap-2">
          <h3 className="text-sm font-semibold">On the bill screen</h3>
          <Keys rows={EDITOR} />
        </section>
      </DialogContent>
    </Dialog>
  );
}
