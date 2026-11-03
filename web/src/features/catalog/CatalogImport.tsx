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

type ImportResult = components["schemas"]["CatalogImportResult"];

const FIELD_LABELS: Record<string, string> = {
  name: "Item name",
  description: "Description",
  unit: "Unit",
  sac_hsn: "HSN/SAC",
  default_rate: "Rate",
  gst_rate: "GST %",
};

/** Items from a CSV / Excel file (B.2): check first, then import, all or nothing. */
export function CatalogImport({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  return (
    <SpreadsheetImport<ImportResult>
      title="Import items"
      label="Items file"
      noun="item"
      nouns="items"
      hint="One item per row. Columns are found by name: item name (needed), description, unit, HSN/SAC, rate, GST % (18 if left empty). Items already in your catalog are not imported twice."
      missingColumns="No header row found. The file needs at least an “Item name” column."
      fieldLabels={FIELD_LABELS}
      samplePath="/api/v1/catalog-items:import-sample"
      sampleName="items-sample"
      upload={async (file, dryRun, key) =>
        unwrap(
          await api.POST("/api/v1/catalog-items:import", {
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
        void queryClient.invalidateQueries({ queryKey: ["catalog-items"] });
      }}
      onClose={onDone}
      preview={(result) => (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>HSN/SAC</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">GST %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.items.slice(0, 100).map((i) => (
                <TableRow key={i.name}>
                  <TableCell>{i.name}</TableCell>
                  <TableCell>{i.unit}</TableCell>
                  <TableCell className="font-mono">{i.sac_hsn}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {i.default_rate ? formatInr(i.default_rate) : "—"}
                  </TableCell>
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
