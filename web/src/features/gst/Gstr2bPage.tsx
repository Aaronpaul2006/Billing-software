import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { formatDate, formatMonthYear } from "@/lib/dates";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

type Row = components["schemas"]["ReconRow"];
type Status = Row["status"];

const STATUS: Record<Status, { label: string; className: string }> = {
  MATCHED: { label: "Matched", className: "bg-success-soft text-success border-success-border" },
  AMOUNTS_DIFFER: {
    label: "Amounts differ",
    className: "bg-warning-soft text-warning border-warning-border",
  },
  NOT_IN_BOOKS: {
    label: "Not in our books",
    className: "bg-info-soft text-info border-info-border",
  },
  NOT_IN_2B: {
    label: "Not in the 2B",
    className: "bg-destructive-soft text-destructive border-destructive-border",
  },
};

function problem(e: unknown): string {
  if (e instanceof ApiError && e.problem.errors?.length)
    return e.problem.errors.map((x) => x.message).join(" ");
  return e instanceof Error ? e.message : "Something went wrong.";
}

function OurDoc({ row }: { row: Row }) {
  const b = row.books;
  if (!b) return <span className="text-muted-foreground">–</span>;
  const to = b.kind === "VENDOR_BILL" ? `/vendor-bills/${b.id}` : `/expenses/${b.id}`;
  return (
    <>
      <Link to={to} className="font-medium hover:underline">
        {b.number || (b.kind === "EXPENSE" ? "Expense" : "Bill")}
      </Link>
      <div className="text-help text-muted-foreground">
        {formatDate(b.doc_date)} · <Money value={b.taxable_value} /> + <Money value={b.tax} />
      </div>
    </>
  );
}

const columns: Column<Row>[] = [
  {
    id: "supplier",
    header: "Supplier",
    card: "title",
    cell: (r) => (
      <>
        <span className="font-medium">{r.supplier_name || r.supplier_gstin}</span>
        <div className="text-help text-muted-foreground">{r.supplier_gstin}</div>
      </>
    ),
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (r) => (
      <span
        className={cn(
          "inline-flex rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
          STATUS[r.status].className,
        )}
      >
        {STATUS[r.status].label}
      </span>
    ),
  },
  {
    id: "portal",
    header: "In the 2B",
    card: "detail",
    cell: (r) =>
      r.portal ? (
        <>
          <span className="font-medium">{r.portal.doc_number}</span>
          {r.portal.doc_type === "CREDIT_NOTE" && (
            <span className="text-muted-foreground"> (credit note)</span>
          )}
          <div className="text-help text-muted-foreground">
            {formatDate(r.portal.doc_date)} · <Money value={r.portal.taxable_value} /> +{" "}
            <Money value={r.portal.tax} />
            {!r.portal.itc_available && " · ITC not available"}
            {r.portal.reverse_charge && " · reverse charge"}
          </div>
        </>
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
  { id: "books", header: "In our books", card: "detail", cell: (r) => <OurDoc row={r} /> },
  {
    id: "note",
    header: "Note",
    card: "detail",
    cell: (r) =>
      r.status === "AMOUNTS_DIFFER" ? (
        <span className="text-sm">
          The 2B shows <Money value={r.taxable_difference} /> more value and{" "}
          <Money value={r.tax_difference} /> more tax{r.note ? `. ${r.note}` : ""}
        </span>
      ) : (
        <span className="text-sm">{r.note || "–"}</span>
      ),
  },
];

function Figure({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="text-figure font-semibold">{children}</p>
      <p className="text-help text-muted-foreground">{hint}</p>
    </div>
  );
}

export function Gstr2bPage() {
  const { role } = useSession();
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState("");
  const [show, setShow] = useState<Status | "">("");
  const returns = useQuery({
    queryKey: ["gstr2b-returns"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/gstr2b-returns", { params: { query: { limit: 24 } } })).results,
  });
  const current = picked || returns.data?.[0]?.id || "";
  const recon = useQuery({
    queryKey: ["gstr2b", current],
    enabled: current !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/gstr2b-returns/{return_id}/reconciliation", {
          params: { path: { return_id: current } },
        }),
      ),
  });
  const upload = useMutation({
    mutationFn: async (file: File) =>
      unwrap(
        await api.POST("/api/v1/gstr2b-returns", {
          body: { file: file as unknown as string },
          bodySerializer: () => {
            const data = new FormData();
            data.append("file", file);
            return data;
          },
          headers: { "Idempotency-Key": newIdempotencyKey() },
        }),
      ),
    onSuccess: (saved) => {
      // the month uploaded again replaces the old upload: never ask for that one again
      setPicked(saved.id);
      queryClient.removeQueries({ queryKey: ["gstr2b"] });
      void queryClient.invalidateQueries({ queryKey: ["gstr2b-returns"] });
    },
  });

  const s = recon.data?.summary;
  const period = recon.data?.gst_return.period;
  const rows = (recon.data?.rows ?? []).filter((r) => !show || r.status === show);

  return (
    <div className="@container">
      <PageHeader
        title="GSTR-2B check"
        description="The input tax credit the GST portal shows for a month, against the bills in our books."
      />
      <Card className="mb-4">
        <CardContent className="grid gap-4 @2xl:grid-cols-2">
          {can(role, "payments.record") && (
            <div>
              <Label htmlFor="gstr2b-file">Upload a GSTR-2B (JSON)</Label>
              <Input
                id="gstr2b-file"
                type="file"
                accept=".json,application/json"
                className="mt-1"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload.mutate(f);
                  e.target.value = "";
                }}
              />
              <p className="text-help text-muted-foreground mt-1">
                On the GST portal: Returns → GSTR-2B → choose the month → Download → JSON. A month
                uploaded again replaces the old one.
              </p>
              {upload.isPending && <p className="mt-2 text-sm">Reading the file…</p>}
              {upload.error && (
                <Alert variant="destructive" className="mt-2">
                  <AlertCircle aria-hidden />
                  <AlertDescription>{problem(upload.error)}</AlertDescription>
                </Alert>
              )}
            </div>
          )}
          {returns.data && returns.data.length > 0 && (
            <div>
              <Label htmlFor="gstr2b-month">Month</Label>
              <NativeSelect
                id="gstr2b-month"
                className="mt-1"
                value={current}
                onChange={(e) => {
                  setPicked(e.target.value);
                }}
              >
                {returns.data.map((r) => (
                  <option key={r.id} value={r.id}>
                    {formatMonthYear(r.period)} · {r.gstin} · {r.doc_count} documents
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
        </CardContent>
      </Card>

      {returns.data?.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No GSTR-2B uploaded yet. Upload a month to see which bills the suppliers have reported.
        </p>
      )}
      {recon.error && <ErrorState error={recon.error} />}
      {s && (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle>
              <h2>{formatMonthYear(period)}</h2>
            </CardTitle>
            <CardDescription>
              {s.matched} matched · {s.amounts_differ} with different amounts · {s.not_in_books} not
              in our books · {s.not_in_2b} not in the 2B
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 @2xl:grid-cols-2 @5xl:grid-cols-4">
            <Figure label="ITC in the 2B" hint="Available, credit notes taken off">
              <Money value={s.itc_in_2b} />
            </Figure>
            <Figure label="Matched" hint="In the 2B and our books alike">
              <Money value={s.itc_matched} />
            </Figure>
            <Figure label="Not in our books" hint="Record these bills to claim it">
              <Money value={s.itc_not_in_books} />
            </Figure>
            <Figure label="At risk" hint="Claimed by us, not reported by the supplier">
              <span className={cn(s.itc_at_risk !== "0.00" && "text-destructive")}>
                <Money value={s.itc_at_risk} />
              </span>
            </Figure>
          </CardContent>
        </Card>
      )}
      {recon.data && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <label htmlFor="gstr2b-show" className="text-muted-foreground text-sm">
              Show
            </label>
            <NativeSelect
              id="gstr2b-show"
              className="w-auto"
              value={show}
              onChange={(e) => {
                setShow(e.target.value as Status | "");
              }}
            >
              <option value="">All</option>
              {(Object.keys(STATUS) as Status[]).map((k) => (
                <option key={k} value={k}>
                  {STATUS[k].label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <DataTable
            label="GSTR-2B against our books"
            rows={rows}
            columns={columns}
            rowKey={(r) => `${r.status}:${r.portal?.id ?? ""}:${r.books?.id ?? ""}`}
            rowLabel={(r) => `${r.supplier_name} ${r.portal?.doc_number ?? r.books?.number ?? ""}`}
            empty={{ title: "Nothing here", description: "Choose another filter above." }}
          />
        </>
      )}
    </div>
  );
}
