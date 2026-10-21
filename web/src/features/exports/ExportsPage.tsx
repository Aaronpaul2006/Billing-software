import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate, periodRange } from "@/features/dashboard/periods";
import { errorMessage } from "@/lib/errors";

import { KIND_LABELS, downloadExport, fileSize, useExports } from "./exports";
import type { Export } from "./exports";

type Kind = components["schemas"]["ExportRequest"]["kind"];
type Format = components["schemas"]["ExportRequest"]["format"];

const DATED: Kind[] = ["DOCUMENTS", "PAYMENTS", "EXPENSES"];
const WITH_BOOK: Kind[] = ["DOCUMENTS", "RECEIVABLES"];

/** GSTR-1 is usually filed for the month just ended. */
function lastMonth(): string {
  const today = new Date();
  return isoDate(new Date(today.getFullYear(), today.getMonth() - 1, 1)).slice(0, 7);
}

function ExportForm() {
  const queryClient = useQueryClient();
  const [search] = useSearchParams();
  const year = periodRange("this_fy", new Date());
  const [kind, setKind] = useState<Kind>(search.get("kind") === "GSTR1" ? "GSTR1" : "DOCUMENTS");
  const [format, setFormat] = useState<Format>("XLSX");
  const [period, setPeriod] = useState(search.get("period") ?? lastMonth());
  const [registrationId, setRegistrationId] = useState("");
  const registrations = useQuery({
    queryKey: ["gst-registrations", "regular"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/gst-registrations")).results.filter(
        (r) => r.registration_type === "REGULAR" && r.is_active,
      ),
    enabled: kind === "GSTR1",
  });
  const chosenRegistration = registrationId || registrations.data?.[0]?.id || "";
  const [from, setFrom] = useState(year.from);
  const [to, setTo] = useState(year.to);
  const [book, setBook] = useState<"ALL" | "GST" | "NON_GST">("ALL");
  const [key, setKey] = useState(newIdempotencyKey);
  const make = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exports", {
          body:
            kind === "GSTR1"
              ? {
                  kind,
                  format: "JSON",
                  params: { gst_registration_id: chosenRegistration, period },
                }
              : {
                  kind,
                  format,
                  params: {
                    ...(DATED.includes(kind) ? { from, to } : {}),
                    ...(WITH_BOOK.includes(kind) ? { book } : {}),
                  },
                },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      setKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: ["exports"] });
    },
  });
  return (
    <Card>
      <CardContent>
        <form
          aria-label="New export"
          className="grid gap-4 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            make.mutate();
          }}
        >
          <Field id="export-kind" label="What">
            <NativeSelect
              id="export-kind"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as Kind);
              }}
            >
              {(Object.keys(KIND_LABELS) as Export["kind"][]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABELS[k]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          {kind === "GSTR1" ? (
            <>
              <Field id="export-registration" label="GST registration">
                <NativeSelect
                  id="export-registration"
                  value={chosenRegistration}
                  onChange={(e) => {
                    setRegistrationId(e.target.value);
                  }}
                >
                  {registrations.data?.length === 0 && (
                    <option value="">No regular registration</option>
                  )}
                  {registrations.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.gstin} · {r.state_name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field id="export-period" label="Month">
                <Input
                  id="export-period"
                  type="month"
                  value={period}
                  onChange={(e) => {
                    setPeriod(e.target.value);
                  }}
                />
              </Field>
              <p className="text-muted-foreground text-sm sm:col-span-3">
                A JSON file for the GST offline tool. Import it into the tool and check it before
                you file.
              </p>
            </>
          ) : (
            <Field id="export-format" label="File">
              <NativeSelect
                id="export-format"
                value={format}
                onChange={(e) => {
                  setFormat(e.target.value as Format);
                }}
              >
                <option value="XLSX">Excel (.xlsx)</option>
                <option value="CSV">CSV</option>
              </NativeSelect>
            </Field>
          )}
          {kind === "GSTR1" ? null : WITH_BOOK.includes(kind) ? (
            <Field id="export-book" label="Books">
              <NativeSelect
                id="export-book"
                value={book}
                onChange={(e) => {
                  setBook(e.target.value as typeof book);
                }}
              >
                <option value="ALL">All</option>
                <option value="GST">GST</option>
                <option value="NON_GST">Non-GST</option>
              </NativeSelect>
            </Field>
          ) : (
            <div />
          )}
          {DATED.includes(kind) && (
            <>
              <Field id="export-from" label="From">
                <Input
                  id="export-from"
                  type="date"
                  value={from}
                  onChange={(e) => {
                    setFrom(e.target.value);
                  }}
                />
              </Field>
              <Field id="export-to" label="To">
                <Input
                  id="export-to"
                  type="date"
                  value={to}
                  onChange={(e) => {
                    setTo(e.target.value);
                  }}
                />
              </Field>
              <div />
            </>
          )}
          {make.error && (
            <Alert variant="destructive" className="sm:col-span-3">
              <AlertCircle aria-hidden />
              <AlertDescription>
                {make.error instanceof ApiError && make.error.problem.errors?.length
                  ? make.error.problem.errors.map((x) => x.message).join(" ")
                  : errorMessage(make.error)}
              </AlertDescription>
            </Alert>
          )}
          <div className="sm:col-span-3">
            <Button type="submit" disabled={make.isPending}>
              Make the file
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function ExportRow({ x }: { x: Export }) {
  const params = x.params as { from?: string; to?: string; book?: string; period?: string };
  return (
    <li className="flex flex-wrap items-center gap-3 border-b py-3 text-sm last:border-b-0">
      <div className="grid min-w-48 flex-1 gap-0.5">
        <span className="font-medium">
          {KIND_LABELS[x.kind]} · {x.format}
        </span>
        <span className="text-muted-foreground text-xs">
          {params.from && params.to ? `${params.from} to ${params.to}` : ""}
          {params.period ?? ""}
          {params.book && params.book !== "ALL" ? ` · ${params.book.replace("_", "-")} books` : ""}
          {" · "}
          {new Date(x.created_at).toLocaleString("en-IN")}
        </span>
        {x.warnings.map((w) => (
          <span key={w} className="text-xs text-amber-700 dark:text-amber-400">
            {w}
          </span>
        ))}
        {x.status === "FAILED" && <span className="text-destructive text-xs">{x.error}</span>}
      </div>
      {x.status === "PENDING" && (
        <span role="status" className="text-muted-foreground flex items-center gap-1">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Making…
        </span>
      )}
      {x.status === "FAILED" && <Badge variant="destructive">Failed</Badge>}
      {x.status === "READY" && (
        <>
          <span className="text-muted-foreground text-xs">
            {x.row_count ?? 0} rows · {fileSize(x.size_bytes)}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void downloadExport(x.id);
            }}
          >
            <Download aria-hidden /> Download {x.file_name}
          </Button>
        </>
      )}
    </li>
  );
}

export function ExportsPage() {
  const exports = useExports();
  return (
    <>
      <PageHeader
        title="Exports"
        description="Registers for your accountant, as Excel or CSV. Files are kept for 7 days."
      />
      <div className="grid max-w-3xl gap-6">
        <ExportForm />
        <section aria-label="Your exports">
          <h2 className="mb-2 font-medium">Your exports</h2>
          {exports.error ? (
            <ErrorState error={exports.error} />
          ) : !exports.data ? (
            <Skeleton className="h-24 w-full" />
          ) : exports.data.length === 0 ? (
            <p className="text-muted-foreground text-sm">Nothing exported in the last 7 days.</p>
          ) : (
            <ul>
              {exports.data.map((x) => (
                <ExportRow key={x.id} x={x} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
