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

import { LINE_FIELD_LABELS } from "./items";

type ParseResult = components["schemas"]["ParseLinesResult"];
export type ParsedLine = components["schemas"]["ParsedLine"];

/** Bill lines from a CSV / Excel file (B.7): checked by the server, then added to the draft. */
export function LinesImport({
  onLines,
  onDone,
}: {
  onLines: (lines: ParsedLine[]) => void;
  onDone: () => void;
}) {
  return (
    <SpreadsheetImport<ParseResult>
      title="Import lines"
      label="Lines file"
      noun="line"
      nouns="lines"
      hint="One line per row. Columns are found by name: description and quantity (needed), unit, rate, discount or discount %, GST %, HSN/SAC. Rows without a quantity (headings, totals) are skipped. You can also paste rows copied from Excel straight into a line."
      missingColumns="No header row found. The file needs at least “Description” and “Quantity” columns."
      fieldLabels={LINE_FIELD_LABELS}
      samplePath="/api/v1/documents:lines-sample"
      sampleName="lines-sample"
      upload={async (file, dryRun) => {
        const result = unwrap(
          await api.POST("/api/v1/documents:parse-lines", {
            body: { file: file as unknown as string },
            bodySerializer: () => {
              const data = new FormData();
              data.append("file", file);
              return data;
            },
          }),
        );
        // The server only checks; "import" here means adding the lines to this bill.
        return { ...result, dry_run: dryRun };
      }}
      onImported={(result) => {
        onLines(result.lines);
      }}
      onClose={onDone}
      preview={(result) => (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Description</TableHead>
              <TableHead className="text-right">Quantity</TableHead>
              <TableHead>Unit</TableHead>
              <TableHead className="text-right">Rate</TableHead>
              <TableHead className="text-right">GST %</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.lines.slice(0, 100).map((l, i) => (
              <TableRow key={`${String(i)}-${l.description}`}>
                <TableCell className="max-w-96 truncate">{l.description}</TableCell>
                <TableCell className="text-right tabular-nums">{formatQty(l.quantity)}</TableCell>
                <TableCell>{l.unit}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInr(l.rate)}</TableCell>
                <TableCell className="text-right">
                  {l.gst_rate ? formatQty(l.gst_rate) : ""}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    />
  );
}
