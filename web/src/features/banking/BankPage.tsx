import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileUp } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { LoadMore } from "@/components/LoadMore";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { useToast } from "@/components/toast-context";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { formatDate } from "@/lib/dates";
import { readJson, writeJson } from "@/lib/appearance";
import { ifMatch } from "@/lib/forms";
import { formatInr } from "@/lib/money";

type Line = components["schemas"]["BankLine"];
type Preview = components["schemas"]["StatementPreview"];
type Status = "OPEN" | "MATCHED" | "IGNORED";

const FIELD_LABELS: { field: string; label: string; optional?: boolean }[] = [
  { field: "date", label: "Date" },
  { field: "narration", label: "Narration / description" },
  { field: "reference", label: "Cheque / ref no.", optional: true },
  { field: "money_out", label: "Withdrawal (money out)" },
  { field: "money_in", label: "Deposit (money in)" },
  { field: "balance", label: "Balance", optional: true },
];
const LAST_ACCOUNT = "app.bank.account";
const MAPPINGS = "app.bank.mappings"; // header row -> columns, per bank layout

function problem(e: unknown): string {
  return e instanceof ApiError && e.problem.errors?.length
    ? e.problem.errors.map((x) => x.message).join(" ")
    : e instanceof Error
      ? e.message
      : "Something went wrong.";
}

type Mappings = Record<string, Record<string, string>>;

function lastAccount(): string {
  const v = readJson(LAST_ACCOUNT);
  return typeof v === "string" ? v : "";
}

function savedMappings(): Mappings {
  const v = readJson(MAPPINGS);
  return v !== null && typeof v === "object" ? (v as Mappings) : {};
}

function form(file: File, fields: Record<string, string>): FormData {
  const data = new FormData();
  data.append("file", file);
  for (const [k, v] of Object.entries(fields)) data.append(k, v);
  return data;
}

async function previewFile(file: File, mapping?: Record<string, string>) {
  return unwrap(
    await api.POST("/api/v1/bank-statements/preview", {
      body: { file: file as unknown as string },
      bodySerializer: () => form(file, mapping ? { mapping: JSON.stringify(mapping) } : {}),
    }),
  );
}

async function importFile(file: File, account: string, mapping?: Record<string, string>) {
  return unwrap(
    await api.POST("/api/v1/bank-statements/import", {
      body: { file: file as unknown as string, account_label: account },
      bodySerializer: () =>
        form(file, {
          account_label: account,
          ...(mapping ? { mapping: JSON.stringify(mapping) } : {}),
        }),
      headers: { "Idempotency-Key": newIdempotencyKey() },
    }),
  );
}

/** Import a statement: name the account, choose the file, see what is in it, import. */
function ImportPanel({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [account, setAccount] = useState(lastAccount);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const remembered = (headers: string[]) => savedMappings()[headers.join("|")];

  const look = useMutation({
    mutationFn: async (args: { file: File; mapping?: Record<string, string> }) =>
      previewFile(args.file, args.mapping),
    onSuccess: (p, args) => {
      setPreview(p);
      if (!p.ready && !args.mapping) {
        const known = remembered(p.headers);
        if (known && file) {
          setMapping(known);
          look.mutate({ file, mapping: known });
        }
      }
    },
    onError: (e) => {
      setMessage(problem(e));
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose the file.");
      const chosen = Object.keys(mapping).length ? mapping : undefined;
      return importFile(file, account.trim(), chosen);
    },
    onSuccess: (done) => {
      writeJson(LAST_ACCOUNT, account.trim());
      if (preview && Object.keys(mapping).length) {
        writeJson(MAPPINGS, {
          ...savedMappings(),
          [preview.headers.join("|")]: mapping,
        });
      }
      void queryClient.invalidateQueries({ queryKey: ["bank-lines"] });
      void queryClient.invalidateQueries({ queryKey: ["bank-accounts"] });
      toast({
        message: `Added ${String(done.added)} ${done.added === 1 ? "line" : "lines"}${done.duplicates ? `; ${String(done.duplicates)} were imported before` : ""}.`,
        tone: "success",
      });
      onDone();
    },
    onError: (e) => {
      setMessage(problem(e));
    },
  });

  return (
    <Card className="mb-6 max-w-3xl">
      <CardHeader>
        <CardTitle>
          <h2>Import a statement</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        {message && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="bank-account" label="Which account" hint="e.g. HDFC current 1234">
            <Input
              id="bank-account"
              value={account}
              onChange={(e) => {
                setAccount(e.target.value);
              }}
            />
          </Field>
          <Field id="bank-file" label="The bank's statement (CSV or Excel)">
            <Input
              id="bank-file"
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setFile(f);
                setPreview(null);
                setMapping({});
                setMessage(null);
                if (f) look.mutate({ file: f });
              }}
            />
          </Field>
        </div>
        {preview && !preview.ready && (
          <div className="grid gap-3 rounded-md border p-3">
            <p className="text-sm font-medium">
              Which column is which? (Remembered for this bank's layout.)
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              {FIELD_LABELS.map(({ field, label, optional }) => (
                <Field key={field} id={`map-${field}`} label={label}>
                  <NativeSelect
                    id={`map-${field}`}
                    value={mapping[field] ?? ""}
                    onChange={(e) => {
                      setMapping({ ...mapping, [field]: e.target.value });
                    }}
                  >
                    <option value="">{optional ? "None" : "Choose…"}</option>
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
              ))}
            </div>
            <div>
              <Button
                variant="outline"
                disabled={!file || look.isPending}
                onClick={() => {
                  if (file) look.mutate({ file, mapping });
                }}
              >
                Check again
              </Button>
            </div>
          </div>
        )}
        {preview?.ready && (
          <div role="status" className="grid gap-2 text-sm">
            <p className="font-medium">
              {preview.line_count} {preview.line_count === 1 ? "line" : "lines"} found
              {preview.skipped_rows.length > 0 &&
                ` (${String(preview.skipped_rows.length)} rows without a date left out: totals and summaries)`}
              .
            </p>
            <ul aria-label="First lines" className="text-muted-foreground grid gap-1">
              {preview.lines.slice(0, 5).map((l) => (
                <li key={l.row} className="flex justify-between gap-4">
                  <span className="truncate">
                    {formatDate(l.line_date)} · {l.narration}
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {l.money_in !== "0.00"
                      ? `+${formatInr(l.money_in)}`
                      : `−${formatInr(l.money_out)}`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={!preview?.ready || !account.trim() || save.isPending}
            onClick={() => {
              setMessage(null);
              save.mutate();
            }}
          >
            {preview?.ready ? `Import ${String(preview.line_count)} lines` : "Import"}
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** What a line is: a suggestion, a new payment, or nothing to match. */
function MatchPanel({ line, onClose }: { line: Line; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const money = line.money_in !== "0.00" ? line.money_in : line.money_out;
  const incoming = line.money_in !== "0.00";
  const [party, setParty] = useState<PickedParty | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: async (args: { action: "match" | "record" | "ignore"; body: object }) =>
      unwrap(
        await api.POST(
          `/api/v1/bank-lines/{line_id}/${args.action}` as "/api/v1/bank-lines/{line_id}/match",
          {
            params: { path: { line_id: line.id } },
            body: args.body as never,
            headers: { "If-Match": ifMatch(line.version), "Idempotency-Key": newIdempotencyKey() },
          },
        ),
      ),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["bank-lines"] });
      void queryClient.invalidateQueries({ queryKey: ["payments"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      toast({
        message: saved.status === "IGNORED" ? "Line ignored." : "Line matched.",
        tone: "success",
      });
      onClose();
    },
    onError: (e) => {
      setError(problem(e));
    },
  });
  return (
    <div className="grid gap-5">
      <p className="text-sm">
        {formatDate(line.line_date)} · {line.narration}
        {line.reference ? ` · ${line.reference}` : ""}
        <br />
        <span className="font-semibold">
          {incoming ? "Money in" : "Money out"} {formatInr(money)}
        </span>
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <section aria-label="Suggestions" className="grid gap-2">
        <h3 className="text-sm font-semibold">What it may be</h3>
        {line.suggestions.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Nothing recorded with this amount near this date.
          </p>
        ) : (
          <ul className="grid gap-2">
            {line.suggestions.map((s) => (
              <li
                key={`${s.kind}-${s.id}`}
                className="flex flex-wrap items-center gap-2 rounded-md border p-2"
              >
                <span className="min-w-40 flex-1 text-sm">
                  <span className="font-medium">{s.title}</span>
                  <span className="text-muted-foreground"> · {s.party_name}</span>
                </span>
                <Button
                  size="sm"
                  disabled={act.isPending}
                  onClick={() => {
                    setError(null);
                    if (s.kind === "payment")
                      act.mutate({ action: "match", body: { payment_id: s.id } });
                    else if (s.kind === "vendor_payment")
                      act.mutate({ action: "match", body: { vendor_payment_id: s.id } });
                    else if (s.kind === "bill")
                      act.mutate({
                        action: "record",
                        body: {
                          party_id: s.party_id,
                          allocations: [{ document_id: s.id, amount: money }],
                        },
                      });
                    else
                      act.mutate({
                        action: "record",
                        body: {
                          vendor_party_id: s.party_id,
                          vendor_allocations: [{ vendor_bill_id: s.id, amount: money }],
                        },
                      });
                  }}
                >
                  {s.kind === "payment" || s.kind === "vendor_payment"
                    ? "This is it"
                    : "Record payment for it"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-label="Record a new payment" className="grid gap-2">
        <h3 className="text-sm font-semibold">
          {incoming ? "Record it as a payment from…" : "Record it as a payment to…"}
        </h3>
        <PartyPicker
          id="bank-party"
          role={incoming ? "customer" : "vendor"}
          value={party}
          onChange={setParty}
        />
        <div>
          <Button
            variant="outline"
            disabled={!party || act.isPending}
            onClick={() => {
              if (!party) return;
              setError(null);
              act.mutate({
                action: "record",
                body: incoming ? { party_id: party.id } : { vendor_party_id: party.id },
              });
            }}
          >
            Record {formatInr(money)}
          </Button>
        </div>
        <p className="text-help text-muted-foreground">
          Set it against their bills from the payment's page afterwards.
        </p>
      </section>
      <section aria-label="Not a payment" className="grid gap-2">
        <h3 className="text-sm font-semibold">Nothing to match</h3>
        <Input
          aria-label="Why (optional)"
          placeholder="e.g. bank charges, transfer to own account"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
        <div>
          <Button
            variant="ghost"
            disabled={act.isPending}
            onClick={() => {
              act.mutate({ action: "ignore", body: { note: note.trim() || null } });
            }}
          >
            Ignore this line
          </Button>
        </div>
      </section>
    </div>
  );
}

export function BankPage() {
  const queryClient = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState<Status>("OPEN");
  const [account, setAccount] = useState("");
  const [open, setOpen] = useState<Line | null>(null);
  const accounts = useQuery({
    queryKey: ["bank-accounts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/bank-lines/accounts")).results,
  });
  const lines = useInfiniteQuery({
    queryKey: ["bank-lines", { status, account }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/bank-lines", {
          params: {
            query: {
              status,
              ...(account ? { account_label: account } : {}),
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const reopen = useMutation({
    mutationFn: async (l: Line) =>
      unwrap(
        await api.POST("/api/v1/bank-lines/{line_id}/reopen", {
          params: { path: { line_id: l.id } },
          headers: { "If-Match": ifMatch(l.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["bank-lines"] });
    },
  });
  const rows = lines.data?.pages.flatMap((p) => p.results) ?? [];
  const columns: Column<Line>[] = [
    {
      id: "narration",
      header: "Narration",
      card: "title",
      className: "whitespace-normal",
      cell: (l) => (
        <>
          <span className="font-medium">{l.narration}</span>
          <div className="text-help text-muted-foreground">
            {[l.reference, l.account_label, l.note].filter(Boolean).join(" · ")}
          </div>
        </>
      ),
    },
    { id: "date", header: "Date", card: "subtitle", cell: (l) => formatDate(l.line_date) },
    {
      id: "in",
      header: "Money in",
      align: "right",
      card: "amount",
      cell: (l) => (l.money_in !== "0.00" ? <Money value={l.money_in} /> : null),
    },
    {
      id: "out",
      header: "Money out",
      align: "right",
      card: "amount",
      cell: (l) => (l.money_out !== "0.00" ? <Money value={l.money_out} /> : null),
    },
    {
      id: "action",
      header: "Match",
      card: "badge",
      cell: (l) =>
        l.status === "OPEN" ? (
          <Button
            size="sm"
            variant={l.suggestions.length ? "default" : "outline"}
            onClick={() => {
              setOpen(l);
            }}
          >
            {l.suggestions.length ? "Match…" : "Choose…"}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            disabled={reopen.isPending}
            onClick={() => {
              reopen.mutate(l);
            }}
          >
            Reopen
          </Button>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Bank statements"
        description="Import the bank's statement and say what each line is. Nothing is matched without you."
        actions={
          !importing && (
            <Button
              onClick={() => {
                setImporting(true);
              }}
            >
              <FileUp aria-hidden /> Import a statement
            </Button>
          )
        }
      />
      {importing && (
        <ImportPanel
          onDone={() => {
            setImporting(false);
          }}
        />
      )}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Show" className="flex gap-1">
          {(
            [
              ["OPEN", "To match"],
              ["MATCHED", "Matched"],
              ["IGNORED", "Ignored"],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={status === value ? "default" : "outline"}
              aria-pressed={status === value}
              onClick={() => {
                setStatus(value);
              }}
            >
              {label}
            </Button>
          ))}
        </div>
        {(accounts.data?.length ?? 0) > 1 && (
          <NativeSelect
            aria-label="Account"
            className="w-auto"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value);
            }}
          >
            <option value="">All accounts</option>
            {accounts.data?.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </NativeSelect>
        )}
      </div>
      {lines.error ? (
        <ErrorState error={lines.error} />
      ) : (
        <>
          <DataTable
            label="Bank lines"
            rows={rows}
            columns={columns}
            rowKey={(l) => l.id}
            rowLabel={(l) => `${formatDate(l.line_date)} ${l.narration}`}
            loading={lines.isPending}
            empty={
              status === "OPEN"
                ? {
                    title: "Nothing to match",
                    description:
                      "Import your bank's statement to check it against what is recorded.",
                  }
                : { title: status === "MATCHED" ? "Nothing matched yet" : "Nothing ignored" }
            }
          />
          <LoadMore query={lines} />
        </>
      )}
      <Sheet
        open={open !== null}
        onOpenChange={(o) => {
          if (!o) setOpen(null);
        }}
      >
        <SheetContent
          side="right"
          closeLabel="Close"
          className="w-full max-w-lg overflow-y-auto p-4 pt-12 sm:w-[32rem] sm:max-w-lg"
        >
          <SheetTitle className="text-section">What is this line?</SheetTitle>
          <SheetDescription className="sr-only">
            Match it to a payment, record a new payment, or ignore it.
          </SheetDescription>
          <div className="mt-4">
            {open && (
              <MatchPanel
                line={open}
                onClose={() => {
                  setOpen(null);
                }}
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
