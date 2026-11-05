import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/dates";

import { documentKey } from "./api";

const when = (iso: string) => formatDateTime(iso);

/** Who changed what on the bill, and when, in plain words (B.11). Loaded when opened. */
export function DocumentHistory({ documentId }: { documentId: string }) {
  const [open, setOpen] = useState(false);
  const history = useQuery({
    // under the document's key: anything that refreshes the bill refreshes this
    queryKey: [...documentKey(documentId), "history"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/history", {
          params: { path: { document_id: documentId } },
        }),
      ).results,
    enabled: open,
  });
  return (
    <section aria-labelledby="history-heading" className="grid gap-3">
      <h2 id="history-heading" className="text-base font-semibold">
        <Button
          variant="ghost"
          className="-ml-3"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          <History aria-hidden /> Change history
        </Button>
      </h2>
      {open && history.error && <ErrorState error={history.error} />}
      {open && history.isPending && <Skeleton className="h-24 w-full max-w-2xl" />}
      {open && history.data && (
        <ol aria-label="Changes, newest first" className="grid max-w-2xl gap-3 border-l pl-4">
          {history.data.map((e, i) => (
            <li key={`${e.at}-${String(i)}`} className="grid gap-1 text-sm">
              <p>
                <span className="font-medium">{e.summary}</span>
                <span className="text-muted-foreground">
                  {" "}
                  · {e.actor_name ?? "System"} · {when(e.at)}
                </span>
              </p>
              {e.details.length > 0 && (
                <ul className="text-muted-foreground list-disc pl-5">
                  {e.details.map((d, j) => (
                    <li key={String(j)}>{d}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {history.data.length === 0 && (
            <li className="text-muted-foreground text-sm">No changes recorded yet.</li>
          )}
        </ol>
      )}
    </section>
  );
}
