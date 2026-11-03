import { useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SpreadsheetImport } from "@/features/imports/SpreadsheetImport";
import { formatInr, formatQty } from "@/lib/money";

type ImportResult = components["schemas"]["BoqImportResult"];

const FIELD_LABELS: Record<string, string> = {
  item_code: "Item code",
  description: "Description",
  unit: "Unit",
  contract_qty: "Quantity",
  rate: "Rate",
  gst_rate: "GST %",
  sac_hsn: "HSN/SAC",
};

/** Upload a CSV / XLSX BOQ: check first (nothing saved), then import, all or nothing. */
export function BoqImport({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  return (
    <SpreadsheetImport<ImportResult>
      title="Import BOQ"
      label="BOQ file"
      noun="item"
      nouns="items"
      hint="Columns are found by name: item code, description, unit, quantity, rate; GST %, HSN/SAC and variation are optional. Title, heading and total rows are skipped."
      missingColumns="No header row found. The file needs columns for item code, description, unit, quantity and rate."
      fieldLabels={FIELD_LABELS}
      upload={async (file, dryRun, key) =>
        unwrap(
          await api.POST("/api/v1/projects/{project_id}/boq-items:import", {
            params: { path: { project_id: projectId } },
            body: { file: file as unknown as string, dry_run: dryRun },
            bodySerializer: (body) => {
              const data = new FormData();
              data.append("file", body.file as unknown as File);
              data.append("dry_run", String(body.dry_run));
              return data;
            },
            headers: { "Idempotency-Key": key },
          }),
        )
      }
      onImported={() => {
        void queryClient.invalidateQueries({ queryKey: ["boq", projectId] });
        void queryClient.invalidateQueries({ queryKey: ["boq-progress", projectId] });
      }}
      onClose={onDone}
      preview={(result) => (
        <>
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
              {result.items.slice(0, 100).map((i) => (
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
          {result.items.length > 100 && (
            <p className="text-muted-foreground text-xs">
              Showing the first 100 of {result.items.length}.
            </p>
          )}
        </>
      )}
    />
  );
}
