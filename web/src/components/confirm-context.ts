import { createContext, useContext } from "react";
import type { ReactNode } from "react";

export interface ConfirmOptions {
  /** The question, e.g. "Delete this draft?" */
  title: string;
  /** What happens, in plain words. */
  description?: ReactNode;
  /** The button that goes ahead, e.g. "Delete draft". */
  confirmLabel: string;
  cancelLabel?: string;
  /** "danger": a red button, for what cannot be undone. */
  tone?: "default" | "danger";
}

export type Ask = (options: ConfirmOptions) => Promise<boolean>;

export const ConfirmContext = createContext<Ask | null>(null);

/** `if (await confirm({ title, confirmLabel })) …` (the dialog: ConfirmDialog.tsx). */
export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext);
  if (!ask) throw new Error("useConfirm needs a ConfirmProvider (see App.tsx Providers).");
  return ask;
}
