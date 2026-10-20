import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatInr, formatQty } from "@/lib/money";

import { describeRowError } from "./rows";

type ImportResult = components["schemas"]["BoqImportResult"];

const FILE_MESSAGES: Record<string, string> = {
  missing_columns:
    "No header row found. The file needs columns for item code, description, unit, quantity and rate.",
  no_rows: "The file has no item rows.",
  not_utf8: "Save the file as CSV UTF-8 or as an Excel (.xlsx) file.",
  unsupported_file: "Upload a CSV or an Excel (.xlsx) file.",
  file_too_large: "The file is too large (at most 5 MB).",
  too_many_rows: "Too many rows (at most 5,000 per import).",
};

/**
 * Upload a CSV / XLSX BOQ: first a dry run (nothing saved) shows what would be
 * imported or which rows are wrong; then import, all or nothing.
 */
export function BoqImport({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [keys, setKeys] = useState({ check: newIdempotencyKey(), save: newIdempotencyKey() });
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<number | null>(null);

  const send = useMutation({
    mutationFn: async ({ dryRun }: { dryRun: boolean }) => {
      if (!file) throw new Error("Choose a file.");
      return unwrap(
        await api.POST("/api/v1/projects/{project_id}/boq-items:import", {
          params: { path: { project_id: projectId } },
          body: { file: file as unknown as string, dry_run: dryRun },
          bodySerializer: (body) => {
            const data = new FormData();
            data.append("file", body.file as unknown as File);
            data.append("dry_run", String(body.dry_run));
            return data;
          },
          headers: { "Idempotency-Key": dryRun ? keys.check : keys.save },
        }),
      );
    },
    onSuccess: (result) => {
      if (result.dry_run) {
        setPreview(result);
      } else {
        setDone(result.count);
        setPreview(null);
        void queryClient.invalidateQueries({ queryKey: ["boq", projectId] });
        void queryClient.invalidateQueries({ queryKey: ["boq-progress", projectId] });
      }
    },
  });

  const problem = send.error instanceof ApiError ? send.error.problem : null;
  const rowErrors = problem?.code === "validation_error" ? (problem.errors ?? []) : [];
  const fileError = problem?.errors?.find((e) => e.field === "file");

  return (
    <section aria-label="Import BOQ" className="bg-muted/40 grid gap-4 rounded-lg border p-4">
      <div className="grid gap-2">
        <Label htmlFor="boq-file">BOQ file (CSV or Excel)</Label>
        <Input
          id="boq-file"
          type="file"
          accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setKeys({ check: newIdempotencyKey(), save: newIdempotencyKey() });
            setPreview(null);
            setDone(null);
            send.reset();
          }}
        />
        <p className="text-muted-foreground text-xs">
          Columns are found by name: item code, description, unit, quantity, rate; GST %, HSN/SAC
          and variation are optional. Title, heading and total rows are skipped.
        </p>
      </div>

      {done !== null && (
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>
            Imported {done} {done === 1 ? "item" : "items"}.
          </AlertDescription>
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
              (FILE_MESSAGES[fileError.code] ?? fileError.message)
            ) : rowErrors.length ? (
              <ul className="grid gap-0.5">
                {rowErrors.map((e) => (
                  <li key={`${e.field ?? ""}-${e.code}`}>
                    <span className="font-medium">{describeRowError(e.field)}</span>: {e.message}
                  </li>
                ))}
              </ul>
            ) : (
              send.error.message
            )}
          </AlertDescription>
        </Alert>
      )}

      {preview && (
        <div className="grid gap-3">
          <p className="text-sm">
            <strong>{preview.count}</strong> {preview.count === 1 ? "item" : "items"} ready to
            import.
            {preview.skipped_rows.length > 0 &&
              ` Skipped heading / total rows: ${preview.skipped_rows.join(", ")}.`}
            {preview.ignored_columns.length > 0 &&
              ` Ignored columns: ${preview.ignored_columns.join(", ")}.`}
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">GST %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.items.slice(0, 100).map((i) => (
                <TableRow key={i.item_code}>
                  <TableCell className="font-mono">{i.item_code}</TableCell>
                  <TableCell className="max-w-96 truncate">{i.description}</TableCell>
                  <TableCell>{i.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatQty(i.contract_qty)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatInr(i.rate)}</TableCell>
                  <TableCell className="text-right">{formatQty(i.gst_rate)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {preview.items.length > 100 && (
            <p className="text-muted-foreground text-xs">
              Showing the first 100 of {preview.items.length}.
            </p>
          )}
        </div>
      )}

      <div className="flex gap-2">
        {preview ? (
          <Button
            disabled={send.isPending}
            onClick={() => {
              send.mutate({ dryRun: false });
            }}
          >
            Import {preview.count} {preview.count === 1 ? "item" : "items"}
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
        <Button variant="ghost" onClick={onDone}>
          Close
        </Button>
      </div>
    </section>
  );
}
