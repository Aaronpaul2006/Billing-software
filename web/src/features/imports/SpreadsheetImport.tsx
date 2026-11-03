import { useMutation } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, FileUp } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

import { authFetch, newIdempotencyKey } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";

/** What every import endpoint answers (BOQ, items, clients, bill lines). */
export interface ImportResult {
  dry_run: boolean;
  count: number;
  skipped_rows: number[];
  ignored_columns: string[];
}

const FILE_MESSAGES: Record<string, string> = {
  no_rows: "The file has no rows to import.",
  not_utf8: "Save the file as CSV UTF-8 or as an Excel (.xlsx) file.",
  unsupported_file: "Upload a CSV or an Excel (.xlsx) file.",
  file_too_large: "The file is too large (at most 5 MB).",
  too_many_rows: "Too many rows (at most 5,000 per import).",
};

/** "rows[7].default_rate" -> "Row 7 · Rate" (with the import's own field labels). */
function rowLabel(field: string | null, labels: Record<string, string>): string {
  const m = /^rows\[(\d+)\]\.?(.*)$/.exec(field ?? "");
  if (!m) return field ?? "File";
  const name = m[2] ?? "";
  return `Row ${m[1] ?? ""}${name ? ` · ${labels[name] ?? name}` : ""}`;
}

/** Save a sample file from the API (signed in, so not a plain link). */
async function downloadSample(path: string, fileName: string): Promise<void> {
  const response = await authFetch(new Request(`${window.location.origin}${path}`));
  if (!response.ok) throw new Error("Could not download the sample file.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Upload a CSV / Excel file: first a check (nothing saved) shows what would
 * be imported or which rows are wrong; then import, all or nothing.
 */
export function SpreadsheetImport<R extends ImportResult>({
  title,
  label,
  hint,
  noun,
  nouns,
  missingColumns,
  fieldLabels = {},
  samplePath,
  sampleName,
  upload,
  preview,
  onImported,
  onClose,
}: {
  /** The region's name, e.g. "Import items". */
  title: string;
  /** The file field's label, e.g. "Items file". */
  label: string;
  hint: ReactNode;
  noun: string;
  nouns: string;
  /** The message when no header row has the needed columns. */
  missingColumns: string;
  fieldLabels?: Record<string, string>;
  /** API path of the sample file, without ?type= (e.g. "/api/v1/catalog-items:import-sample"). */
  samplePath?: string;
  sampleName?: string;
  upload: (file: File, dryRun: boolean, idempotencyKey: string) => Promise<R>;
  preview: (result: R) => ReactNode;
  onImported?: (result: R) => void;
  onClose: () => void;
}) {
  const fileId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [keys, setKeys] = useState({ check: newIdempotencyKey(), save: newIdempotencyKey() });
  const [checked, setChecked] = useState<R | null>(null);
  const [done, setDone] = useState<number | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  const send = useMutation({
    mutationFn: async ({ dryRun }: { dryRun: boolean }) => {
      if (!file) throw new Error("Choose a file.");
      return upload(file, dryRun, dryRun ? keys.check : keys.save);
    },
    onSuccess: (result) => {
      if (result.dry_run) {
        setChecked(result);
      } else {
        setDone(result.count);
        setChecked(null);
        onImported?.(result);
      }
    },
  });

  const problem = send.error instanceof ApiError ? send.error.problem : null;
  const rowErrors = problem?.code === "validation_error" ? (problem.errors ?? []) : [];
  const fileError = problem?.errors?.find((e) => e.field === "file");
  const many = (n: number) => `${String(n)} ${n === 1 ? noun : nouns}`;

  return (
    <section aria-label={title} className="bg-muted/40 grid gap-4 rounded-lg border p-4">
      <div className="grid gap-2">
        <Label htmlFor={fileId}>{label} (CSV or Excel)</Label>
        <Input
          id={fileId}
          type="file"
          accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setKeys({ check: newIdempotencyKey(), save: newIdempotencyKey() });
            setChecked(null);
            setDone(null);
            send.reset();
          }}
        />
        <p className="text-muted-foreground text-xs">{hint}</p>
        {samplePath && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Sample file to fill in:</span>
            {(["xlsx", "csv"] as const).map((type) => (
              <Button
                key={type}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSampleError(null);
                  downloadSample(
                    `${samplePath}?type=${type}`,
                    `${sampleName ?? "sample"}.${type}`,
                  ).catch((e: unknown) => {
                    setSampleError(errorMessage(e));
                  });
                }}
              >
                <Download aria-hidden /> {type === "xlsx" ? "Excel" : "CSV"}
              </Button>
            ))}
            {sampleError && <span className="text-destructive">{sampleError}</span>}
          </div>
        )}
      </div>

      {done !== null && (
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>Imported {many(done)}.</AlertDescription>
        </Alert>
      )}

      {send.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertTitle>
            {rowErrors.length && !fileError
              ? "Fix these rows and upload again"
              : "Could not import"}
          </AlertTitle>
          <AlertDescription>
            {fileError ? (
              fileError.code === "missing_columns" ? (
                missingColumns
              ) : (
                (FILE_MESSAGES[fileError.code] ?? fileError.message)
              )
            ) : rowErrors.length ? (
              <ul className="grid gap-0.5">
                {rowErrors.map((e) => (
                  <li key={`${e.field ?? ""}-${e.code}`}>
                    <span className="font-medium">{rowLabel(e.field, fieldLabels)}</span>:{" "}
                    {e.message}
                  </li>
                ))}
              </ul>
            ) : (
              send.error.message
            )}
          </AlertDescription>
        </Alert>
      )}

      {checked && (
        <div className="grid gap-3">
          <p className="text-sm">
            <strong>{many(checked.count)}</strong> ready to import.
            {checked.skipped_rows.length > 0 &&
              ` Skipped heading / total rows: ${checked.skipped_rows.join(", ")}.`}
            {checked.ignored_columns.length > 0 &&
              ` Ignored columns: ${checked.ignored_columns.join(", ")}.`}
          </p>
          {preview(checked)}
        </div>
      )}

      <div className="flex gap-2">
        {checked ? (
          <Button
            disabled={send.isPending}
            onClick={() => {
              send.mutate({ dryRun: false });
            }}
          >
            Import {many(checked.count)}
          </Button>
        ) : (
          <Button
            disabled={!file || send.isPending}
            onClick={() => {
              send.mutate({ dryRun: true });
            }}
          >
            <FileUp aria-hidden /> Check file
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </section>
  );
}
