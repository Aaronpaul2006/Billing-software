import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ConfirmContext } from "@/components/confirm-context";
import type { Ask, ConfirmOptions } from "@/components/confirm-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * The app's own "are you sure?" dialog (D.3), in place of the browser's
 * confirm() box: a clear question, what will happen, and named buttons.
 * Esc, the overlay or Cancel answer "no"; focus goes back where it was.
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [asking, setAsking] = useState<ConfirmOptions | null>(null);
  const [open, setOpen] = useState(false);
  const answer = useRef<((yes: boolean) => void) | null>(null);
  /** What had the focus when the question came up: it gets it back afterwards. */
  const returnTo = useRef<HTMLElement | null>(null);

  const ask = useCallback<Ask>(
    (options) =>
      new Promise<boolean>((resolve) => {
        answer.current?.(false); // a new question replaces an unanswered one
        answer.current = resolve;
        returnTo.current =
          document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setAsking(options);
        setOpen(true);
      }),
    [],
  );

  const close = (yes: boolean) => {
    answer.current?.(yes);
    answer.current = null;
    setOpen(false); // the last question stays in place while the dialog closes
  };

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      <Dialog
        open={open}
        onOpenChange={(open) => {
          if (!open) close(false);
        }}
      >
        {asking && (
          <DialogContent
            role="alertdialog"
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              returnTo.current?.focus();
            }}
          >
            <DialogTitle>{asking.title}</DialogTitle>
            {asking.description ? (
              <DialogDescription>{asking.description}</DialogDescription>
            ) : (
              <DialogDescription className="sr-only">{asking.title}</DialogDescription>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  close(false);
                }}
              >
                {asking.cancelLabel ?? "Cancel"}
              </Button>
              <Button
                variant={asking.tone === "danger" ? "destructive" : "default"}
                onClick={() => {
                  close(true);
                }}
              >
                {asking.confirmLabel}
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </ConfirmContext.Provider>
  );
}
