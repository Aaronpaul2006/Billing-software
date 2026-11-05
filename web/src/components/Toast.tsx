import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ToastContext } from "@/components/toast-context";
import type { Show, ToastItem } from "@/components/toast-context";
import { cn } from "@/lib/utils";

const ICONS = { success: CheckCircle2, info: Info, warning: TriangleAlert } as const;

function ToastView({ toast, dismiss }: { toast: ToastItem; dismiss: (id: number) => void }) {
  const [paused, setPaused] = useState(false);
  const { id, duration, action } = toast;
  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(
      () => {
        dismiss(id);
      },
      duration ?? (action ? 8000 : 5000),
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [paused, id, duration, action, dismiss]);
  const onClose = () => {
    dismiss(id);
  };
  const tone = toast.tone ?? "success";
  const Icon = ICONS[tone];
  return (
    <div
      className="bg-popover text-popover-foreground flex items-center gap-3 rounded-lg border p-3 text-sm shadow-md"
      onMouseEnter={() => {
        setPaused(true);
      }}
      onMouseLeave={() => {
        setPaused(false);
      }}
      onFocus={() => {
        setPaused(true);
      }}
      onBlur={() => {
        setPaused(false);
      }}
    >
      <Icon
        className={cn(
          "size-4 shrink-0",
          tone === "success" && "text-success",
          tone === "info" && "text-info",
          tone === "warning" && "text-warning",
        )}
        aria-hidden
      />
      <span className="flex-1">{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          className="text-primary rounded-sm px-2 py-1 font-medium hover:underline focus-visible:ring-[3px] focus-visible:outline-none"
          onClick={() => {
            toast.action?.onClick();
            onClose();
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button
        type="button"
        aria-label="Dismiss"
        className="text-muted-foreground hover:text-foreground rounded-sm p-1 focus-visible:ring-[3px] focus-visible:outline-none"
        onClick={onClose}
      >
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/**
 * Short messages at the bottom of the screen (D.3): "Saved", "Line 3
 * removed · Undo". Read out by screen readers (a polite live region); they
 * close by themselves, but not while the pointer or focus is on them.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const show = useCallback<Show>((options) => {
    const id = next.current++;
    setToasts((all) => [...all.slice(-2), { ...options, id }]); // at most three at once
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((x) => x.id !== id));
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        role="region"
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] grid gap-2 sm:right-4 sm:left-auto sm:w-96 [&>*]:pointer-events-auto"
      >
        {toasts.map((t) => (
          <ToastView key={t.id} toast={t} dismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
