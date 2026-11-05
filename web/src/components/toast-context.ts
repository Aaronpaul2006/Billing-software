import { createContext, useContext } from "react";

export interface ToastOptions {
  message: string;
  tone?: "success" | "info" | "warning";
  /** e.g. { label: "Undo", onClick } — only for things that can really be undone. */
  action?: { label: string; onClick: () => void };
  /** How long it stays, in ms (default 5 s, 8 s with an action). */
  duration?: number;
}

export interface ToastItem extends ToastOptions {
  id: number;
}

export type Show = (options: ToastOptions) => void;

export const ToastContext = createContext<Show | null>(null);

/** `toast({ message: "Saved" })` (the messages: Toast.tsx). */
export function useToast(): Show {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast needs a ToastProvider (see App.tsx Providers).");
  return show;
}
