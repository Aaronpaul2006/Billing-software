import { Check, Circle, CircleDot, X } from "lucide-react";

import { formatDate } from "@/lib/dates";
import { cn } from "@/lib/utils";

import { RECEIVABLE_TYPES } from "./api";
import type { Document } from "./api";
import { documentStatus } from "./status";

type StepState = "done" | "now" | "next" | "stopped";

interface Step {
  label: string;
  state: StepState;
  detail?: string;
}

const SPOKEN: Record<StepState, string> = {
  done: "done",
  now: "now",
  next: "still to come",
  stopped: "stopped here",
};

/** Where a document is on its way, in plain words (D.8). */
function timelineSteps(doc: Document): Step[] {
  const status = documentStatus(doc);
  const issuedOn = doc.issued_at ? formatDate(doc.issued_at) : undefined;
  const draft: Step = { label: "Draft", state: doc.status === "DRAFT" ? "now" : "done" };
  if (doc.status === "DRAFT") {
    const rest =
      doc.doc_type === "QUOTATION"
        ? ["Sent to the client", "Accepted"]
        : RECEIVABLE_TYPES.has(doc.doc_type)
          ? ["Issued", "Paid"]
          : ["Issued"];
    return [draft, ...rest.map((label) => ({ label, state: "next" as const }))];
  }
  if (doc.status === "CANCELLED") {
    return [
      draft,
      { label: "Issued", state: "done", detail: issuedOn },
      { label: "Cancelled", state: "stopped" },
    ];
  }
  if (doc.doc_type === "QUOTATION") {
    const sent: Step = { label: "Sent to the client", state: "done", detail: issuedOn };
    if (doc.status === "ACCEPTED") return [draft, sent, { label: "Accepted", state: "now" }];
    if (doc.status === "DECLINED") return [draft, sent, { label: "Declined", state: "stopped" }];
    return [draft, { ...sent, state: "now" }, { label: "Accepted or declined", state: "next" }];
  }
  if (!RECEIVABLE_TYPES.has(doc.doc_type)) {
    return [draft, { label: "Issued", state: "now", detail: issuedOn }];
  }
  if (status === "paid") {
    return [
      draft,
      { label: "Issued", state: "done", detail: issuedOn },
      { label: "Paid", state: "now" },
    ];
  }
  if (status === "part_paid") {
    return [
      draft,
      { label: "Issued", state: "done", detail: issuedOn },
      { label: "Part paid", state: "now" },
      { label: "Paid", state: "next" },
    ];
  }
  return [
    draft,
    {
      label: status === "overdue" ? "Issued, now overdue" : "Issued",
      state: "now",
      detail: issuedOn,
    },
    { label: "Paid", state: "next" },
  ];
}

function Icon({ state }: { state: StepState }) {
  const cls = "size-4 shrink-0";
  if (state === "done") return <Check className={cn(cls, "text-success")} aria-hidden />;
  if (state === "now") return <CircleDot className={cn(cls, "text-primary")} aria-hidden />;
  if (state === "stopped") return <X className={cn(cls, "text-destructive")} aria-hidden />;
  return <Circle className={cn(cls, "text-muted-foreground")} aria-hidden />;
}

export function BillTimeline({ doc }: { doc: Document }) {
  const steps = timelineSteps(doc);
  return (
    <ol
      aria-label="Where this document is"
      className="flex flex-wrap items-center gap-x-1 gap-y-2 text-sm"
    >
      {steps.map((s, i) => (
        <li
          key={s.label}
          aria-current={s.state === "now" || s.state === "stopped" ? "step" : undefined}
          className="flex items-center gap-1"
        >
          {i > 0 && (
            <span
              aria-hidden
              className={cn("bg-border mx-1 h-px w-6", s.state !== "next" && "bg-foreground/40")}
            />
          )}
          <Icon state={s.state} />
          <span
            className={cn(
              s.state === "next" && "text-muted-foreground",
              (s.state === "now" || s.state === "stopped") && "font-semibold",
            )}
          >
            {s.label}
            {s.detail && <span className="text-muted-foreground font-normal"> · {s.detail}</span>}
            <span className="sr-only"> ({SPOKEN[s.state]})</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
