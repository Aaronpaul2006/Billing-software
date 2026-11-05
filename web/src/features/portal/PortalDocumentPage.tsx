import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, FileDown, X } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { useConfirm } from "@/components/confirm-context";
import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import { TotalsPanel } from "@/features/documents/TotalsPanel";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";
import { formatInr, formatQty } from "@/lib/money";
import { formatDate } from "@/lib/dates";
import { StatusBadge } from "@/components/StatusBadge";
import { documentStatus } from "@/features/documents/status";

import { portalDocumentKey, portalDocumentQuery } from "./api";
import type { PortalDocumentDetail } from "./api";

function answerMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "quotation_expired":
        return "This quotation has expired. Ask us for a new one.";
      case "not_issued":
        return "This quotation has already been answered.";
      case "stale_version":
        return "This quotation changed meanwhile. Reload the page and try again.";
    }
  }
  return errorMessage(error);
}

type Line = PortalDocumentDetail["lines"][number];

/** A bill's lines: a table on wide screens, cards on phones (D.12). */
const LINE_COLUMNS: Column<Line>[] = [
  {
    id: "description",
    header: "Description",
    card: "title",
    className: "whitespace-normal",
    cell: (l) => (
      <>
        <span className="font-normal">{l.description}</span>
        {l.sac_hsn && <div className="text-help text-muted-foreground">HSN/SAC {l.sac_hsn}</div>}
      </>
    ),
  },
  {
    id: "quantity",
    header: "Quantity",
    align: "right",
    card: "subtitle",
    cell: (l) => (
      <span className="tabular-nums">
        {formatQty(l.quantity)} {l.unit}
        <span className="lg:hidden"> × {formatInr(l.rate)}</span>
      </span>
    ),
  },
  {
    id: "rate",
    header: "Rate",
    align: "right",
    card: "hidden",
    cell: (l) => <Money value={l.rate} />,
  },
  { id: "gst", header: "GST", align: "right", cell: (l) => `${l.gst_rate} %` },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "amount",
    cell: (l) => <Money value={l.taxable_value} />,
  },
];

export function PortalDocumentPage() {
  const { documentId = "" } = useParams();
  const query = useQuery(portalDocumentQuery(documentId));
  if (query.isPending) return <Skeleton className="h-64 w-full" />;
  if (query.isError) return <ErrorState error={query.error} />;
  return <DocumentView doc={query.data} />;
}

function DocumentView({ doc }: { doc: PortalDocumentDetail }) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const path = { document_id: doc.id };

  const answer = useMutation({
    mutationFn: async (accept: boolean) =>
      unwrap(
        accept
          ? await api.POST("/api/v1/portal/documents/{document_id}/accept", {
              params: { path },
              headers: { "If-Match": ifMatch(doc.version) },
            })
          : await api.POST("/api/v1/portal/documents/{document_id}/decline", {
              params: { path },
              headers: { "If-Match": ifMatch(doc.version) },
            }),
      ),
    onSuccess: (updated) => {
      setNotice(null);
      queryClient.setQueryData(portalDocumentKey(doc.id), updated);
      void queryClient.invalidateQueries({ queryKey: ["portal", "documents"] });
    },
    onError: (e) => {
      setNotice(answerMessage(e));
    },
  });

  const openPdf = async () => {
    setNotice(null);
    const tab = window.open("", "_blank"); // opened now, so pop-up blockers allow it
    try {
      const result = await api.GET("/api/v1/portal/documents/{document_id}/pdf", {
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
      setNotice(errorMessage(e));
    }
  };

  const openQuote = doc.doc_type === "QUOTATION" && doc.status === "ISSUED";
  const confirmAndAnswer = (accept: boolean) => {
    void confirm(
      accept
        ? {
            title: `Accept quotation ${doc.doc_number ?? ""}?`,
            description: `For ${formatInr(doc.totals.grand_total)}. The business is told at once.`,
            confirmLabel: "Accept quotation",
          }
        : {
            title: `Decline quotation ${doc.doc_number ?? ""}?`,
            description: "The business is told at once.",
            confirmLabel: "Decline quotation",
            tone: "danger",
          },
    ).then((yes) => {
      if (yes) answer.mutate(accept);
    });
  };

  return (
    <>
      <Link
        to="/portal/bills"
        className="text-muted-foreground mb-2 flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="size-4" aria-hidden /> Bills & quotes
      </Link>
      <PageHeader
        title={`${DOC_TYPE_LABELS[doc.doc_type]} ${doc.doc_number ?? ""}`}
        description={
          <>
            <StatusBadge status={documentStatus(doc)} /> {formatDate(doc.doc_date)}
            {doc.project_name ? ` · ${doc.project_name}` : ""}
            {doc.due_date ? ` · due ${formatDate(doc.due_date)}` : ""}
            {doc.valid_until ? ` · valid until ${doc.valid_until}` : ""}
          </>
        }
        actions={
          <>
            {openQuote && (
              <>
                <Button
                  disabled={answer.isPending}
                  onClick={() => {
                    confirmAndAnswer(true);
                  }}
                >
                  <Check aria-hidden /> Accept
                </Button>
                <Button
                  variant="outline"
                  disabled={answer.isPending}
                  onClick={() => {
                    confirmAndAnswer(false);
                  }}
                >
                  <X aria-hidden /> Decline
                </Button>
              </>
            )}
            <Button variant="outline" onClick={() => void openPdf()}>
              <FileDown aria-hidden /> PDF
            </Button>
          </>
        }
      />
      {notice && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle aria-hidden />
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardContent className="grid gap-6 pt-6">
          <DataTable
            label="Lines"
            rows={doc.lines}
            columns={LINE_COLUMNS}
            rowKey={(l) => String(l.line_no)}
          />
          <div className="ml-auto w-full max-w-sm">
            <TotalsPanel
              totals={doc.totals}
              intraState={doc.totals.igst === "0.00"}
              showSettlement={doc.status === "ISSUED" && doc.doc_type !== "QUOTATION"}
            />
          </div>
          {doc.terms && (
            <p className="text-muted-foreground text-sm whitespace-pre-line">{doc.terms}</p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
