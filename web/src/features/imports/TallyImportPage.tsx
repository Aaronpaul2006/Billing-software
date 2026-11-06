import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/toast-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";

type Result = components["schemas"]["TallyImportResult"];
type Row = components["schemas"]["TallyRow"];
type Kind = Row["kind"];
type Show = "ALL" | Row["status"];

const KINDS: { kind: Kind; key: "clients" | "vendors" | "items"; one: string; many: string }[] = [
  { kind: "CLIENT", key: "clients", one: "client", many: "clients" },
  { kind: "VENDOR", key: "vendors", one: "vendor", many: "vendors" },
  { kind: "ITEM", key: "items", one: "item", many: "items" },
];
const KIND_LABEL: Record<Kind, string> = { CLIENT: "Client", VENDOR: "Vendor", ITEM: "Item" };
const STATUS: Record<Row["status"], { label: string; className: string }> = {
  NEW: { label: "New", className: "bg-success-soft text-success border-success-border" },
  EXISTS: { label: "Already here", className: "bg-muted text-muted-foreground border-border" },
  PROBLEM: {
    label: "Left out",
    className: "bg-destructive-soft text-destructive border-destructive-border",
  },
};
const MESSAGES: Record<string, string> = {
  not_tally_xml:
    "This is not an XML file exported from Tally. Export the masters as XML (Data Interchange).",
  no_masters: "No ledgers or stock items in this file. Export the masters, not the vouchers.",
  file_too_large: "The file is too large (at most 20 MB).",
  nothing_new: "Nothing new to import: everything in the file is already here.",
};

function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const code = e.problem.errors?.[0]?.code;
    if (code && MESSAGES[code]) return MESSAGES[code];
    if (e.status === 403) return "Your role cannot add clients, vendors or items.";
    return e.problem.errors?.map((x) => x.message).join(" ") ?? e.message;
  }
  return "Could not reach the server. Check your connection.";
}

function send(file: File, dryRun: boolean, kinds: Kind[] = []) {
  return api.POST("/api/v1/tally-imports", {
    body: { file: file as unknown as string, dry_run: dryRun, kinds },
    bodySerializer: () => {
      const data = new FormData();
      data.append("file", file);
      data.append("dry_run", String(dryRun));
      for (const k of kinds) data.append("kinds", k);
      return data;
    },
    headers: { "Idempotency-Key": newIdempotencyKey() },
  });
}

const columns: Column<Row>[] = [
  {
    id: "name",
    header: "Name",
    card: "title",
    cell: (r) => <span className="font-medium">{r.name}</span>,
  },
  { id: "kind", header: "Type", card: "subtitle", cell: (r) => KIND_LABEL[r.kind] },
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
    id: "detail",
    header: "GSTIN / HSN",
    card: "detail",
    cell: (r) =>
      r.detail ? <span className="text-sm">{r.detail}</span> : <span aria-hidden>–</span>,
  },
  {
    id: "message",
    header: "Note",
    card: "detail",
    cell: (r) =>
      r.message ? (
        <span className={cn("text-sm", r.status === "PROBLEM" && "text-destructive")}>
          {r.message}
        </span>
      ) : (
        <span aria-hidden>–</span>
      ),
  },
];

function HowToExport() {
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle>
          <h2>1. Export the masters from Tally</h2>
        </CardTitle>
        <CardDescription>
          The menus differ a little between versions; the file is the same.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm @2xl:grid-cols-2">
        <div>
          <p className="font-medium">TallyPrime</p>
          <ol className="text-muted-foreground mt-1 list-decimal space-y-1 pl-5">
            <li>Open the company, then Export (Alt+E) → Masters.</li>
            <li>Choose All Masters and the format XML (Data Interchange).</li>
            <li>Send. Tally saves Master.xml in its export folder.</li>
          </ol>
        </div>
        <div>
          <p className="font-medium">Tally.ERP 9</p>
          <ol className="text-muted-foreground mt-1 list-decimal space-y-1 pl-5">
            <li>Gateway of Tally → Display → List of Accounts.</li>
            <li>Press Alt+E to export; set the format to XML (Data Interchange).</li>
            <li>Export, and note where the file is saved.</li>
          </ol>
        </div>
      </CardContent>
    </Card>
  );
}

export function TallyImportPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Result | null>(null);
  const [done, setDone] = useState<Result | null>(null);
  const [chosen, setChosen] = useState<Kind[]>([]);
  const [show, setShow] = useState<Show>("ALL");

  const look = useMutation({
    mutationFn: async (f: File) => unwrap(await send(f, true)),
    onSuccess: (p) => {
      setPreview(p);
      setDone(null);
      setChosen(KINDS.filter((k) => p[k.key].new > 0).map((k) => k.kind));
      setShow(KINDS.some((k) => p[k.key].problems > 0) ? "PROBLEM" : "ALL");
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose the file first.");
      return unwrap(await send(file, false, chosen));
    },
    onSuccess: (r) => {
      setDone(r);
      setPreview(null);
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      void queryClient.invalidateQueries({ queryKey: ["catalog-items"] });
      toast({ message: `Imported from Tally: ${added(r)}.`, tone: "success" });
    },
  });

  const willAdd = preview
    ? KINDS.filter((k) => chosen.includes(k.kind)).reduce((n, k) => n + preview[k.key].new, 0)
    : 0;
  const rows = (preview?.rows ?? []).filter((r) => show === "ALL" || r.status === show);
  const error = look.error ?? save.error;

  return (
    <div className="@container max-w-5xl">
      <PageHeader
        title="Import from Tally"
        description="Bring in your clients, vendors and items from Tally, so you start with the lists you already have."
      />
      <HowToExport />
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>
            <h2>2. Choose the file</h2>
          </CardTitle>
          <CardDescription>
            Nothing is saved until you import. Names and GSTINs you already have are skipped, so the
            same file can be imported again.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Label htmlFor="tally-file">Tally masters file (XML)</Label>
          <Input
            id="tally-file"
            type="file"
            accept=".xml,text/xml,application/xml"
            className="mt-1 max-w-md"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setPreview(null);
              save.reset();
              if (f) look.mutate(f);
            }}
          />
          {look.isPending && (
            <p className="text-muted-foreground mt-3 text-sm">Reading the file…</p>
          )}
          {error && (
            <Alert variant="destructive" className="mt-4">
              <AlertCircle aria-hidden />
              <AlertDescription>{problem(error)}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {done?.added && (
        <Alert className="mb-4">
          <CheckCircle2 aria-hidden />
          <AlertTitle>Imported: {added(done)}</AlertTitle>
          <AlertDescription>
            <p>
              See them under{" "}
              <Link to="/parties" className="text-primary font-medium hover:underline">
                Clients &amp; vendors
              </Link>{" "}
              and{" "}
              <Link to="/catalog" className="text-primary font-medium hover:underline">
                Catalog
              </Link>
              .
            </p>
          </AlertDescription>
        </Alert>
      )}

      {preview && (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle>
              <h2>3. Check and import</h2>
            </CardTitle>
            <CardDescription>
              {preview.other_ledgers > 0 &&
                `${plural(preview.other_ledgers, "other ledger", "other ledgers")} (bank, sales, taxes and the like) left alone. `}
              Choose what to add.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <fieldset className="grid gap-3 @2xl:grid-cols-3">
              <legend className="sr-only">What to add</legend>
              {KINDS.map((k) => {
                const c = preview[k.key];
                return (
                  <label
                    key={k.kind}
                    className={cn(
                      "border-border flex items-start gap-3 rounded-md border p-3",
                      c.new === 0 && "opacity-60",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="accent-primary mt-1 size-4"
                      disabled={c.new === 0}
                      checked={chosen.includes(k.kind)}
                      onChange={(e) => {
                        setChosen((now) =>
                          e.target.checked ? [...now, k.kind] : now.filter((x) => x !== k.kind),
                        );
                      }}
                    />
                    <span>
                      <span className="block font-medium">
                        Add {plural(c.new, `new ${k.one}`, `new ${k.many}`)}
                      </span>
                      <span className="text-help text-muted-foreground block">
                        {c.exists} already here
                        {c.problems > 0 && (
                          <span className="text-destructive"> · {c.problems} left out</span>
                        )}
                      </span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button
                disabled={willAdd === 0 || save.isPending}
                onClick={() => {
                  save.mutate();
                }}
              >
                <FileUp aria-hidden />
                {save.isPending ? "Importing…" : `Import ${plural(willAdd, "master", "masters")}`}
              </Button>
              <label className="ml-auto flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Show</span>
                <NativeSelect
                  aria-label="Which masters to show"
                  className="w-auto"
                  value={show}
                  onChange={(e) => {
                    setShow(e.target.value as Show);
                  }}
                >
                  <option value="ALL">All</option>
                  <option value="PROBLEM">Left out</option>
                  <option value="NEW">New</option>
                  <option value="EXISTS">Already here</option>
                </NativeSelect>
              </label>
            </div>
          </CardContent>
        </Card>
      )}
      {preview && (
        <DataTable
          label="Masters in the file"
          rows={rows}
          columns={columns}
          rowKey={(r) => `${r.kind}:${r.name}`}
          rowLabel={(r) => r.name}
          empty={{ title: "Nothing to show", description: "Choose another filter above." }}
        />
      )}
    </div>
  );
}

function added(r: Result): string {
  const a = r.added;
  if (!a) return "nothing";
  const parts = [
    a.CLIENT > 0 && plural(a.CLIENT, "client", "clients"),
    a.VENDOR > 0 && plural(a.VENDOR, "vendor", "vendors"),
    a.ITEM > 0 && plural(a.ITEM, "item", "items"),
  ].filter(Boolean) as string[];
  return parts.length > 1
    ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1) ?? ""}`
    : (parts[0] ?? "nothing");
}
