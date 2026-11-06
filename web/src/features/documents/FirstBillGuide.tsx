import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { readJson, writeJson } from "@/lib/appearance";
import { cn } from "@/lib/utils";

export const DISMISSED = "app.guide.firstBill.dismissed";

interface Progress {
  /** A client is chosen. */
  client: boolean;
  /** At least one line has a quantity and a rate. */
  line: boolean;
  /** The draft is saved. */
  saved: boolean;
}

/**
 * The guided first bill (Part B): a slim panel above the bill editor until the
 * business issues its first bill, ticking off each step as it is done.
 * "Skip the guide" hides it for good (in this browser); ?guide=1 brings it back.
 */
export function FirstBillGuide({ progress }: { progress: Progress }) {
  const [params] = useSearchParams();
  const asked = params.get("guide") === "1";
  const [dismissed, setDismissed] = useState(() => readJson(DISMISSED) === true && !asked);
  const setup = useQuery({
    queryKey: ["tenant", "setup"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant/setup")),
    staleTime: 60_000,
    retry: false,
  });
  if (dismissed) return null;
  if (!asked && (!setup.data || setup.data.first_bill)) return null;

  const steps = [
    { done: progress.client, text: "Choose the client (or add one with “New client”)." },
    {
      done: progress.line,
      text: "Add what you are billing: pick an item from your catalog or the project's BOQ, then the quantity and rate.",
    },
    {
      done: progress.saved,
      text: "Check the totals and tax on the right, then Save. Nothing is final yet: a draft can be changed.",
    },
    {
      done: false,
      text: "On the bill's page, look it over and press Issue: it gets its number and its PDF.",
    },
  ];
  const next = steps.findIndex((s) => !s.done);
  return (
    <section
      aria-label="Your first bill"
      className="border-primary/30 bg-primary/5 mb-4 grid gap-2 rounded-lg border p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="text-primary size-4" aria-hidden /> Your first bill, in four steps
        </p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8"
          onClick={() => {
            writeJson(DISMISSED, true);
            setDismissed(true);
          }}
        >
          <X aria-hidden /> Skip the guide
        </Button>
      </div>
      <ol className="grid gap-1.5 text-sm">
        {steps.map((s, i) => (
          <li
            key={s.text}
            aria-current={i === next ? "step" : undefined}
            className={cn("flex gap-2", i === next && "font-medium")}
          >
            {s.done ? (
              <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" aria-label="Done" />
            ) : (
              <Circle className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-label="To do" />
            )}
            <span className={cn(s.done && "text-muted-foreground line-through")}>{s.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
