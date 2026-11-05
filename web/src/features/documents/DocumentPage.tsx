import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileDown, IndianRupee, MoreHorizontal, Pencil } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useSession } from "@/auth/context";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { useConfirm } from "@/components/confirm-context";
import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { ifMatch } from "@/lib/forms";
import { placeName } from "@/lib/india";
import { errorMessage } from "@/lib/errors";
import { compareMoney, formatInr, formatQty } from "@/lib/money";
import { isBlob } from "@/lib/blob";
import { can } from "@/lib/permissions";
import { DocumentSettlement } from "@/features/payments/DocumentSettlement";
import { DocumentReminders } from "@/features/reminders/DocumentReminders";
import { SaveAsTemplate } from "@/features/templates/SaveAsTemplate";
import { formatDate, formatDateTime } from "@/lib/dates";
import { StatusBadge } from "@/components/StatusBadge";
import { documentStatus } from "@/features/documents/status";

import {
  DOC_TYPE_LABELS,
  documentKey,
  documentTitle,
  RECEIVABLE_TYPES,
  supplyNote,
  useDocument,
} from "./api";
import type { DocType, Document } from "./api";
import { BillTimeline } from "./BillTimeline";
import { DocumentHistory } from "./DocumentHistory";
import { IssueReview } from "./IssueReview";
import { SendBill } from "./SendBill";
import type { PrintCopy } from "./sending";
import { TotalsPanel } from "./TotalsPanel";

const CONVERT_TO: Partial<Record<DocType, DocType[]>> = {
  QUOTATION: ["TAX_INVOICE", "PROFORMA", "BILL_OF_SUPPLY"],
  PROFORMA: ["TAX_INVOICE", "BILL_OF_SUPPLY"],
};

/** What went wrong, and what to do about it. */
function actionMessage(error: unknown): ReactNode {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "series_missing":
        return (
          <>
            {error.message}{" "}
            <Link to="/settings/series" className="underline">
              Add a number series
            </Link>
            .
          </>
        );
      case "stale_version":
        return "Someone else changed this document. Reload the page and try again.";
      case "document_settled":
        return "Payments are allocated to this document; unwind them first.";
      default:
        return error.problem.errors?.length
          ? error.problem.errors.map((e) => e.message).join(" ")
          : error.message;
    }
  }
  return errorMessage(error);
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

type Line = Document["lines"][number];

/** A line's measurement sheet (B.9), folded under its description. */
function Measurements({ line }: { line: Line }) {
  if (line.measurements.length === 0) return null;
  const n = line.measurements.length;
  return (
    <details className="mt-1 text-sm">
      <summary className="text-primary cursor-pointer">
        Measurements ({n} {n === 1 ? "row" : "rows"})
      </summary>
      <table className="mt-1 w-full text-xs">
        <caption className="sr-only">Measurements for line {line.line_no}</caption>
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 pr-2 text-left font-medium">Where</th>
            <th className="py-1 pr-2 text-right font-medium">Nos × L × B × H</th>
            <th className="py-1 text-right font-medium">Quantity</th>
          </tr>
        </thead>
        <tbody>
          {line.measurements.map((m) => (
            <tr key={m.row_no} className="border-t">
              <td className="py-1 pr-2">
                {m.description ?? `Row ${String(m.row_no)}`}
                {m.deduct && <span className="text-muted-foreground"> (less)</span>}
              </td>
              <td className="py-1 pr-2 text-right tabular-nums">
                {[m.nos, m.length, m.breadth, m.height]
                  .filter((v): v is string => v !== null)
                  .map(formatQty)
                  .join(" × ")}
              </td>
              <td className="py-1 text-right tabular-nums">
                {m.deduct ? "−" : ""}
                {formatQty(m.quantity)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function lineColumns(doc: Document): Column<Line>[] {
  const ra = doc.is_ra_bill;
  const discount = doc.lines.some((l) => l.discount_amount !== "0.00");
  const cols: (Column<Line> | false)[] = [
    { id: "no", header: "#", card: "hidden", cell: (l) => l.line_no },
    {
      id: "description",
      header: "Description",
      card: "title",
      className: "max-w-[24rem] whitespace-normal",
      cell: (l) => (
        <>
          <span className="font-normal">{l.description}</span>
          {l.sac_hsn && <div className="text-help text-muted-foreground">HSN/SAC {l.sac_hsn}</div>}
          <Measurements line={l} />
        </>
      ),
    },
    ra && {
      id: "previous",
      header: "Previous",
      align: "right",
      cell: (l) => formatQty(l.prev_cumulative_qty),
    },
    {
      id: "quantity",
      header: ra ? "This bill" : "Quantity",
      align: "right",
      card: "subtitle",
      cell: (l) => (
        <span className="tabular-nums">
          {formatQty(l.quantity)} {l.unit}
          <span className="lg:hidden"> × {formatInr(l.rate)}</span>
        </span>
      ),
    },
    ra && {
      id: "uptodate",
      header: "Up to date",
      align: "right",
      cell: (l) => formatQty(l.up_to_date_qty),
    },
    {
      id: "rate",
      header: "Rate",
      align: "right",
      card: "hidden",
      cell: (l) => <Money value={l.rate} />,
    },
    discount && {
      id: "discount",
      header: "Discount",
      align: "right",
      cell: (l) => <Money value={l.discount_amount} />,
    },
    {
      id: "taxable",
      header: "Taxable",
      align: "right",
      cell: (l) => <Money value={l.taxable_value} />,
    },
    { id: "gst", header: "GST %", align: "right", cell: (l) => formatQty(l.gst_rate) },
    {
      id: "amount",
      header: "Amount",
      align: "right",
      card: "amount",
      cell: (l) => <Money value={l.line_total} />,
    },
  ];
  return cols.filter((c): c is Column<Line> => c !== false);
}

function Lines({ doc }: { doc: Document }) {
  return (
    <DataTable
      label="Lines"
      rows={doc.lines}
      columns={lineColumns(doc)}
      rowKey={(l) => String(l.line_no)}
    />
  );
}

type Panel = "none" | "cancel" | "convert" | "alter" | "review";

/** Bills and quotations can be copied into a new draft; notes belong to their bill. */
const DUPLICABLE: ReadonlySet<DocType> = new Set([
  "QUOTATION",
  "PROFORMA",
  "TAX_INVOICE",
  "BILL_OF_SUPPLY",
]);
/** Issued bills are altered (credit / debit note, or cancel and copy), never edited. */
const ALTERABLE: ReadonlySet<DocType> = new Set(["TAX_INVOICE", "BILL_OF_SUPPLY"]);

function Actions({ doc }: { doc: Document }) {
  const confirm = useConfirm();
  const { role } = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Ctrl+Enter in the editor saves and lands here with the final review open (B.14).
  const [panel, setPanel] = useState<Panel>(() =>
    params.get("review") === "1" && doc.status === "DRAFT" ? "review" : "none",
  );
  const [reason, setReason] = useState("");
  const [convertTo, setConvertTo] = useState<DocType>(
    CONVERT_TO[doc.doc_type]?.[0] ?? "TAX_INVOICE",
  );
  const [convertDate, setConvertDate] = useState(() => isoDate(new Date()));
  const [key, setKey] = useState(newIdempotencyKey); // one per action, renewed after it succeeds
  const [copyKey, setCopyKey] = useState(newIdempotencyKey); // the copy after a cancel
  /** Which printed copy (CGST rule 48), chosen at print: "" is the plain PDF. */
  const [copy, setCopy] = useState<"" | PrintCopy>("");
  const [notice, setNotice] = useState<ReactNode>(null);
  const path = { document_id: doc.id };
  const versioned = { "If-Match": ifMatch(doc.version), "Idempotency-Key": key };

  const done = (updated: Document) => {
    setKey(newIdempotencyKey());
    setPanel("none");
    setNotice(null);
    queryClient.setQueryData(documentKey(updated.id), updated);
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };
  const failed = (e: Error) => {
    setNotice(actionMessage(e));
  };

  const issue = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/issue", {
          params: { path },
          headers: versioned,
        }),
      ),
    onSuccess: done,
    onError: failed,
  });
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/cancel", {
          params: { path },
          body: { reason: reason.trim() },
          headers: versioned,
        }),
      ),
    onSuccess: done,
    onError: failed,
  });
  const respond = useMutation({
    mutationFn: async (accept: boolean) =>
      unwrap(
        accept
          ? await api.POST("/api/v1/documents/{document_id}/accept", {
              params: { path },
              headers: versioned,
            })
          : await api.POST("/api/v1/documents/{document_id}/decline", {
              params: { path },
              headers: versioned,
            }),
      ),
    onSuccess: done,
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: async () => {
      unwrap(await api.DELETE("/api/v1/documents/{document_id}", { params: { path } }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void navigate("/documents", { replace: true });
    },
    onError: failed,
  });
  /** Convert, credit note, debit note: each makes a new draft to finish and issue. */
  const derive = useMutation({
    mutationFn: async (kind: "convert" | "credit" | "debit" | "duplicate") => {
      const headers = { "Idempotency-Key": key };
      const today = isoDate(new Date());
      if (kind === "duplicate") {
        return unwrap(
          await api.POST("/api/v1/documents/{document_id}/duplicate", {
            params: { path },
            body: { doc_date: today },
            headers,
          }),
        );
      }
      if (kind === "convert") {
        return unwrap(
          await api.POST("/api/v1/documents/{document_id}/convert", {
            params: { path },
            body: { to: convertTo as "TAX_INVOICE", doc_date: convertDate },
            headers,
          }),
        );
      }
      return unwrap(
        kind === "credit"
          ? await api.POST("/api/v1/documents/{document_id}/credit-notes", {
              params: { path },
              body: { doc_date: today },
              headers,
            })
          : await api.POST("/api/v1/documents/{document_id}/debit-notes", {
              params: { path },
              body: { doc_date: today },
              headers,
            }),
      );
    },
    onSuccess: (created) => {
      setKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void navigate(`/documents/${created.id}/edit`);
    },
    onError: failed,
  });

  /** "Start again": cancel with the reason, then copy into a new draft to correct and issue. */
  const reissue = useMutation({
    mutationFn: async () => {
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/cancel", {
          params: { path },
          body: { reason: reason.trim() },
          headers: versioned,
        }),
      );
      return unwrap(
        await api.POST("/api/v1/documents/{document_id}/duplicate", {
          params: { path },
          body: { doc_date: isoDate(new Date()) },
          headers: { "Idempotency-Key": copyKey },
        }),
      );
    },
    onSuccess: (copy) => {
      setKey(newIdempotencyKey());
      setCopyKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: documentKey(doc.id) });
      void navigate(`/documents/${copy.id}/edit`);
    },
    onError: (e) => {
      void queryClient.invalidateQueries({ queryKey: documentKey(doc.id) }); // maybe cancelled
      failed(e);
    },
  });

  const openPdf = async () => {
    setNotice(null);
    const tab = window.open("", "_blank"); // opened now, so pop-up blockers allow it
    try {
      if (doc.status === "DRAFT" || copy) {
        // drafts and labelled copies are drawn on demand
        const { data, response } = await api.GET("/api/v1/documents/{document_id}/pdf", {
          params: { path, query: copy ? { copy } : {} },
          parseAs: "blob",
        });
        if (!response.ok || !isBlob(data)) throw new Error("No PDF.");
        if (tab) tab.location.href = URL.createObjectURL(data);
        return;
      }
      const result = await api.GET("/api/v1/documents/{document_id}/pdf", {
        params: { path, query: { as: "link" } },
      });
      if (result.response.status === 202) {
        tab?.close();
        setNotice("The PDF is being prepared. Try again in a few seconds.");
        return;
      }
      const link = unwrap(result) as unknown as { url: string };
      if (tab) tab.location.href = link.url;
    } catch (e) {
      tab?.close();
      setNotice(actionMessage(e));
    }
  };

  const busy =
    issue.isPending ||
    cancel.isPending ||
    respond.isPending ||
    remove.isPending ||
    derive.isPending ||
    reissue.isPending;
  const issued = doc.status === "ISSUED";
  const convertible = CONVERT_TO[doc.doc_type] && (issued || doc.status === "ACCEPTED");

  const mayDraft = can(role, "documents.draft");
  const mayIssue = can(role, "documents.issue");
  const owed =
    issued && RECEIVABLE_TYPES.has(doc.doc_type) && compareMoney(doc.totals.outstanding, "0") === 1;
  const firstConversion = CONVERT_TO[doc.doc_type]?.[0] ?? "TAX_INVOICE";

  // One main action for where the document is, a few others beside it, the rest under "More" (D.8).
  let primary: ReactNode = null;
  const others: ReactNode[] = [];
  const more: { label: string; onSelect: () => void; danger?: boolean }[] = [];
  const pdfButton = (
    <Button key="pdf" variant="outline" disabled={busy} onClick={() => void openPdf()}>
      <FileDown aria-hidden /> Preview PDF
    </Button>
  );

  if (doc.status === "DRAFT") {
    if (mayIssue) {
      primary = (
        <Button
          disabled={busy}
          aria-expanded={panel === "review"}
          onClick={() => {
            setPanel("review"); // the final review first; issuing is one more click
          }}
        >
          Issue…
        </Button>
      );
    }
    if (mayDraft) {
      others.push(
        <Button key="edit" variant={primary ? "outline" : "default"} asChild>
          <Link to={`/documents/${doc.id}/edit`}>
            <Pencil aria-hidden /> Edit
          </Link>
        </Button>,
      );
    }
    others.push(pdfButton);
  } else {
    if (doc.doc_type === "QUOTATION" && issued && mayIssue) {
      primary = (
        <Button
          disabled={busy}
          onClick={() => {
            respond.mutate(true);
          }}
        >
          Accepted by client
        </Button>
      );
      others.push(
        <Button
          key="declined"
          variant="outline"
          disabled={busy}
          onClick={() => {
            respond.mutate(false);
          }}
        >
          Declined
        </Button>,
      );
    } else if (convertible && mayDraft) {
      primary = (
        <Button
          disabled={busy}
          onClick={() => {
            derive.mutate("convert"); // the first choice, dated today
          }}
        >
          Make {DOC_TYPE_LABELS[firstConversion].toLowerCase()}
        </Button>
      );
    } else if (owed && can(role, "payments.record")) {
      primary = (
        <Button asChild>
          <Link
            to={`/payments/new?party=${doc.party_id}&name=${encodeURIComponent(doc.party_name)}`}
          >
            <IndianRupee aria-hidden /> Record payment
          </Link>
        </Button>
      );
    }
    if (issued && ALTERABLE.has(doc.doc_type) && mayIssue) {
      others.push(
        <Button
          key="alter"
          variant="outline"
          disabled={busy}
          aria-expanded={panel === "alter"}
          onClick={() => {
            setPanel(panel === "alter" ? "none" : "alter");
          }}
        >
          Alter…
        </Button>,
      );
    }
    more.push({
      label: "Open the PDF",
      onSelect: () => void openPdf(),
    });
    if (convertible && mayDraft && (CONVERT_TO[doc.doc_type]?.length ?? 0) > 1) {
      more.push({
        label: "Other conversion…",
        onSelect: () => {
          setPanel("convert");
        },
      });
    }
  }
  if (DUPLICABLE.has(doc.doc_type) && mayDraft) {
    more.push({
      label: "Duplicate",
      onSelect: () => {
        derive.mutate("duplicate");
      },
    });
  }
  if (issued && !ALTERABLE.has(doc.doc_type) && mayIssue) {
    more.push({
      label: "Cancel document…",
      danger: true,
      onSelect: () => {
        setPanel("cancel");
      },
    });
  }
  if (doc.status === "DRAFT" && mayDraft) {
    more.push({
      label: "Delete draft",
      danger: true,
      onSelect: () => {
        void confirm({
          title: "Delete this draft?",
          description: "The draft is removed for good. Issued bills are never deleted.",
          confirmLabel: "Delete draft",
          tone: "danger",
        }).then((yes) => {
          if (yes) remove.mutate();
        });
      },
    });
  }
  const safe = more.filter((m) => !m.danger);
  const risky = more.filter((m) => m.danger);

  return (
    <div className="grid gap-3">
      <div role="group" aria-label="Actions" className="flex flex-wrap items-center gap-2">
        {primary}
        {others}
        {more.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" disabled={busy}>
                <MoreHorizontal aria-hidden /> More
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {safe.map((m) => (
                <DropdownMenuItem key={m.label} onSelect={m.onSelect}>
                  {m.label}
                </DropdownMenuItem>
              ))}
              {safe.length > 0 && risky.length > 0 && <DropdownMenuSeparator />}
              {risky.map((m) => (
                <DropdownMenuItem
                  key={m.label}
                  className="text-destructive focus:text-destructive"
                  onSelect={m.onSelect}
                >
                  {m.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {doc.status !== "DRAFT" && (
        <div className="flex flex-wrap items-start gap-2">
          <NativeSelect
            aria-label="Copy to print"
            className="w-auto"
            value={copy}
            onChange={(e) => {
              setCopy(e.target.value as "" | PrintCopy);
            }}
          >
            <option value="">No copy label</option>
            <option value="original">Original for recipient</option>
            <option value="duplicate">Duplicate</option>
            <option value="triplicate">Triplicate for supplier</option>
          </NativeSelect>
          <SendBill doc={doc} copy={copy || "original"} />
        </div>
      )}
      {notice && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}

      {panel === "review" && doc.status === "DRAFT" && (
        <IssueReview
          doc={doc}
          busy={busy}
          onIssue={() => {
            issue.mutate();
          }}
          onClose={() => {
            setPanel("none");
          }}
        />
      )}

      {panel === "alter" && (
        <section
          aria-label="Alter this bill"
          className="bg-muted/40 grid max-w-2xl gap-4 rounded-lg border p-4 text-sm"
        >
          <p>
            An issued bill cannot be changed: the law keeps it as it was sent. Choose what you need:
          </p>
          {doc.doc_type === "TAX_INVOICE" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid content-start gap-2 rounded-md border p-3">
                <h3 className="font-medium">Reduce the amount</h3>
                <p className="text-muted-foreground">
                  Less work was done, the rate was too high, or material came back: a credit note
                  takes the difference off this bill.
                </p>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    derive.mutate("credit");
                  }}
                >
                  Make a credit note
                </Button>
              </div>
              <div className="grid content-start gap-2 rounded-md border p-3">
                <h3 className="font-medium">Increase the amount</h3>
                <p className="text-muted-foreground">
                  More work was done or the rate was too low: a debit note adds the extra to this
                  bill.
                </p>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    derive.mutate("debit");
                  }}
                >
                  Make a debit note
                </Button>
              </div>
            </div>
          )}
          <form
            aria-label="Cancel document"
            className="grid gap-2 rounded-md border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              cancel.mutate();
            }}
          >
            <h3 className="font-medium">Start again</h3>
            <p className="text-muted-foreground">
              The bill is wrong (wrong client, wrong items) or should not have been issued: cancel
              it with a reason. Its number stays used and the bill is kept, marked cancelled. A
              corrected copy can be made as a new draft in the same step. Bills that have been paid
              against cannot be cancelled.
            </p>
            <Label htmlFor="cancel-reason">Reason</Label>
            <Input
              id="cancel-reason"
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={busy || reason.trim().length < 3}
                onClick={() => {
                  reissue.mutate();
                }}
              >
                Cancel and make a corrected copy
              </Button>
              <Button
                type="submit"
                variant="destructive"
                disabled={busy || reason.trim().length < 3}
              >
                Cancel document
              </Button>
            </div>
          </form>
        </section>
      )}

      {panel === "cancel" && (
        <form
          aria-label="Cancel document"
          className="bg-muted/40 grid max-w-xl gap-3 rounded-lg border p-4"
          onSubmit={(e) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          <p className="text-sm">
            The number stays used and the document is kept, marked cancelled. It cannot be undone.
          </p>
          <Label htmlFor="cancel-reason">Reason</Label>
          <Input
            id="cancel-reason"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <div className="flex gap-2">
            <Button type="submit" variant="destructive" disabled={busy || reason.trim().length < 3}>
              Cancel document
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setPanel("none");
              }}
            >
              Keep it
            </Button>
          </div>
        </form>
      )}

      {panel === "convert" && (
        <form
          aria-label="Convert document"
          className="bg-muted/40 grid max-w-xl gap-3 rounded-lg border p-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            derive.mutate("convert");
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="convert-to">Convert to</Label>
            <NativeSelect
              id="convert-to"
              value={convertTo}
              onChange={(e) => {
                setConvertTo(e.target.value as DocType);
              }}
            >
              {(CONVERT_TO[doc.doc_type] ?? []).map((t) => (
                <option key={t} value={t}>
                  {DOC_TYPE_LABELS[t]}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="convert-date">Date of the new document</Label>
            <Input
              id="convert-date"
              type="date"
              value={convertDate}
              onChange={(e) => {
                setConvertDate(e.target.value);
              }}
            />
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={busy || !convertDate}>
              Create draft
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setPanel("none");
              }}
            >
              Close
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export function DocumentPage() {
  const { documentId = "" } = useParams();
  const document = useDocument(documentId);
  if (document.error) return <ErrorState error={document.error} />;
  if (!document.data) return <Skeleton className="h-96 w-full" />;
  const doc = document.data;
  const receivable = RECEIVABLE_TYPES.has(doc.doc_type) && doc.status === "ISSUED";
  return (
    <>
      <Breadcrumbs
        items={
          doc.doc_type === "QUOTATION"
            ? [
                { label: "Quotations", to: "/documents?type=quotations" },
                { label: documentTitle(doc) },
              ]
            : [{ label: "Bills", to: "/documents?type=bills" }, { label: documentTitle(doc) }]
        }
      />
      <PageHeader
        title={documentTitle(doc)}
        badges={<StatusBadge status={documentStatus(doc)} />}
        description={
          <span className="flex items-center gap-2">
            {doc.is_gst_document ? "GST book" : "Non-GST book"}
            {doc.supply_category === "SEZ" && <Badge variant="outline">SEZ</Badge>}
            {doc.supply_category === "EXPORT" && <Badge variant="outline">Export</Badge>}
            {doc.lut && <Badge variant="outline">Under LUT</Badge>}
            {doc.reverse_charge && <Badge variant="outline">Reverse charge</Badge>}
          </span>
        }
      />
      <div className="grid gap-6">
        <BillTimeline doc={doc} />
        <Actions doc={doc} />
        <SaveAsTemplate documentId={doc.id} docType={doc.doc_type} />
        <Card>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-3">
              <Info label="Party">
                <Link
                  to={`/parties/${doc.party_id}`}
                  className="inline-flex min-h-6 items-center hover:underline"
                >
                  {doc.party_name}
                </Link>
              </Info>
              <Info label="Project">
                {doc.project_id ? (
                  <Link
                    to={`/projects/${doc.project_id}`}
                    className="inline-flex min-h-6 items-center hover:underline"
                  >
                    {doc.project_name}
                  </Link>
                ) : (
                  "–"
                )}
              </Info>
              <Info label="Place of supply">
                {placeName(doc.place_of_supply)} (
                {doc.supply_type === "INTRA_STATE" ? "CGST + SGST" : "IGST"})
              </Info>
              <Info label="Date">{formatDate(doc.doc_date)}</Info>
              {doc.doc_type === "QUOTATION" ? (
                <Info label="Valid until">{formatDate(doc.valid_until)}</Info>
              ) : (
                <Info label="Due">{formatDate(doc.due_date)}</Info>
              )}
              {doc.issued_at && <Info label="Issued">{formatDateTime(doc.issued_at)}</Info>}
            </dl>
          </CardContent>
        </Card>
        <Lines doc={doc} />
        <div className="flex flex-wrap justify-between gap-6">
          <div className="text-muted-foreground max-w-prose space-y-2 text-sm whitespace-pre-line">
            {supplyNote(doc) && <p className="text-foreground font-medium">{supplyNote(doc)}</p>}
            {doc.notes && <p>{doc.notes}</p>}
            {doc.terms && <p>{doc.terms}</p>}
          </div>
          <TotalsPanel
            totals={doc.totals}
            intraState={doc.supply_type === "INTRA_STATE"}
            showSettlement={receivable}
            reverseCharge={doc.reverse_charge}
          />
        </div>
        {(receivable || (doc.doc_type === "CREDIT_NOTE" && doc.status === "ISSUED")) && (
          <DocumentSettlement documentId={doc.id} partyId={doc.party_id} />
        )}
        {receivable && (
          <DocumentReminders
            documentId={doc.id}
            partyId={doc.party_id}
            outstanding={doc.totals.outstanding}
          />
        )}
        <DocumentHistory documentId={doc.id} />
      </div>
    </>
  );
}
