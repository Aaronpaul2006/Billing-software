import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Copy, FileDown, Pencil } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isoDate } from "@/features/dashboard/periods";
import { ifMatch } from "@/lib/forms";
import { placeName } from "@/lib/india";
import { errorMessage } from "@/lib/errors";
import { formatInr, formatQty } from "@/lib/money";
import { DocumentSettlement } from "@/features/payments/DocumentSettlement";
import { DocumentReminders } from "@/features/reminders/DocumentReminders";
import { SaveAsTemplate } from "@/features/templates/SaveAsTemplate";

import {
  DOC_TYPE_LABELS,
  documentKey,
  documentTitle,
  RECEIVABLE_TYPES,
  STATUS_LABELS,
  statusVariant,
  supplyNote,
  useDocument,
} from "./api";
import type { DocType, Document } from "./api";
import { TotalsPanel } from "./TotalsPanel";

const CONVERT_TO: Partial<Record<DocType, DocType[]>> = {
  QUOTATION: ["TAX_INVOICE", "PROFORMA", "BILL_OF_SUPPLY"],
  PROFORMA: ["TAX_INVOICE", "BILL_OF_SUPPLY"],
};

function formatDate(iso: string | null): string {
  if (!iso) return "–";
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

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

function Lines({ doc }: { doc: Document }) {
  const ra = doc.is_ra_bill;
  const discount = doc.lines.some((l) => l.discount_amount !== "0.00");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>#</TableHead>
          <TableHead>Description</TableHead>
          {ra && <TableHead className="text-right">Previous</TableHead>}
          <TableHead className="text-right">{ra ? "This bill" : "Quantity"}</TableHead>
          {ra && <TableHead className="text-right">Up to date</TableHead>}
          <TableHead className="text-right">Rate</TableHead>
          {discount && <TableHead className="text-right">Discount</TableHead>}
          <TableHead className="text-right">Taxable</TableHead>
          <TableHead className="text-right">GST %</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {doc.lines.map((l) => (
          <TableRow key={l.line_no}>
            <TableCell>{l.line_no}</TableCell>
            <TableCell className="max-w-[24rem] whitespace-normal">
              {l.description}
              {l.sac_hsn && (
                <div className="text-muted-foreground text-xs">HSN/SAC {l.sac_hsn}</div>
              )}
            </TableCell>
            {ra && (
              <TableCell className="text-right tabular-nums">
                {formatQty(l.prev_cumulative_qty)}
              </TableCell>
            )}
            <TableCell className="text-right tabular-nums">
              {formatQty(l.quantity)} {l.unit}
            </TableCell>
            {ra && (
              <TableCell className="text-right tabular-nums">
                {formatQty(l.up_to_date_qty)}
              </TableCell>
            )}
            <TableCell className="text-right tabular-nums">{formatInr(l.rate)}</TableCell>
            {discount && (
              <TableCell className="text-right tabular-nums">
                {formatInr(l.discount_amount)}
              </TableCell>
            )}
            <TableCell className="text-right tabular-nums">{formatInr(l.taxable_value)}</TableCell>
            <TableCell className="text-right">{formatQty(l.gst_rate)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatInr(l.line_total)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

type Panel = "none" | "cancel" | "convert" | "alter";

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
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [panel, setPanel] = useState<Panel>("none");
  const [reason, setReason] = useState("");
  const [convertTo, setConvertTo] = useState<DocType>(
    CONVERT_TO[doc.doc_type]?.[0] ?? "TAX_INVOICE",
  );
  const [convertDate, setConvertDate] = useState(() => isoDate(new Date()));
  const [key, setKey] = useState(newIdempotencyKey); // one per action, renewed after it succeeds
  const [copyKey, setCopyKey] = useState(newIdempotencyKey); // the copy after a cancel
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
      if (doc.status === "DRAFT") {
        const { data, response } = await api.GET("/api/v1/documents/{document_id}/pdf", {
          params: { path },
          parseAs: "blob",
        });
        if (!response.ok || !(data instanceof Blob)) throw new Error("No PDF.");
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

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        {doc.status === "DRAFT" && (
          <>
            <Button
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    `Issue this ${DOC_TYPE_LABELS[doc.doc_type].toLowerCase()}? It gets the next number and can no longer be edited.`,
                  )
                )
                  issue.mutate();
              }}
            >
              Issue
            </Button>
            <Button variant="outline" asChild>
              <Link to={`/documents/${doc.id}/edit`}>
                <Pencil aria-hidden /> Edit
              </Link>
            </Button>
          </>
        )}
        <Button variant="outline" disabled={busy} onClick={() => void openPdf()}>
          <FileDown aria-hidden /> {doc.status === "DRAFT" ? "Preview PDF" : "PDF"}
        </Button>
        {doc.doc_type === "QUOTATION" && issued && (
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                respond.mutate(true);
              }}
            >
              Accepted by client
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                respond.mutate(false);
              }}
            >
              Declined
            </Button>
          </>
        )}
        {convertible && (
          <>
            <Button
              disabled={busy}
              onClick={() => {
                derive.mutate("convert"); // the first choice, dated today
              }}
            >
              Make {DOC_TYPE_LABELS[CONVERT_TO[doc.doc_type]?.[0] ?? "TAX_INVOICE"].toLowerCase()}
            </Button>
            {(CONVERT_TO[doc.doc_type]?.length ?? 0) > 1 && (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setPanel("convert");
                }}
              >
                Other conversion…
              </Button>
            )}
          </>
        )}
        {DUPLICABLE.has(doc.doc_type) && (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => {
              derive.mutate("duplicate");
            }}
          >
            <Copy aria-hidden /> Duplicate
          </Button>
        )}
        {issued && ALTERABLE.has(doc.doc_type) && (
          <Button
            variant="outline"
            disabled={busy}
            aria-expanded={panel === "alter"}
            onClick={() => {
              setPanel(panel === "alter" ? "none" : "alter");
            }}
          >
            Alter…
          </Button>
        )}
        {issued && !ALTERABLE.has(doc.doc_type) && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setPanel("cancel");
            }}
          >
            Cancel document…
          </Button>
        )}
        {doc.status === "DRAFT" && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              if (window.confirm("Delete this draft?")) remove.mutate();
            }}
          >
            Delete draft
          </Button>
        )}
      </div>

      {notice && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
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
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/documents">
          <ArrowLeft aria-hidden /> Invoices & quotes
        </Link>
      </Button>
      <PageHeader
        title={documentTitle(doc)}
        description={
          <span className="flex items-center gap-2">
            <Badge variant={statusVariant(doc.status)}>{STATUS_LABELS[doc.status]}</Badge>
            {doc.is_gst_document ? "GST book" : "Non-GST book"}
            {doc.supply_category === "SEZ" && <Badge variant="outline">SEZ</Badge>}
            {doc.supply_category === "EXPORT" && <Badge variant="outline">Export</Badge>}
            {doc.lut && <Badge variant="outline">Under LUT</Badge>}
            {doc.reverse_charge && <Badge variant="outline">Reverse charge</Badge>}
          </span>
        }
      />
      <div className="grid gap-6">
        <Actions doc={doc} />
        <SaveAsTemplate documentId={doc.id} docType={doc.doc_type} />
        <Card>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-3">
              <Info label="Party">
                <Link to={`/parties/${doc.party_id}`} className="hover:underline">
                  {doc.party_name}
                </Link>
              </Info>
              <Info label="Project">
                {doc.project_id ? (
                  <Link to={`/projects/${doc.project_id}`} className="hover:underline">
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
              {doc.issued_at && (
                <Info label="Issued">{new Date(doc.issued_at).toLocaleString("en-IN")}</Info>
              )}
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
      </div>
    </>
  );
}
