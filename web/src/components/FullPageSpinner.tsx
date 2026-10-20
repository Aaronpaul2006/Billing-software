import { Loader2 } from "lucide-react";

export function FullPageSpinner() {
  return (
    <div className="flex min-h-svh items-center justify-center" role="status" aria-live="polite">
      <Loader2 className="text-muted-foreground size-6 animate-spin" aria-hidden />
      <span className="sr-only">Loading</span>
    </div>
  );
}
