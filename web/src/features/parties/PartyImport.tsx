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

import { TREATMENTS } from "./gst";

type ImportResult = components["schemas"]["PartyImportResult"];

const FIELD_LABELS: Record<string, string> = {
  display_name: "Name",
  legal_name: "Legal name",
  gstin: "GSTIN",
  gst_treatment: "GST type",
  state_code: "State",
  pan: "PAN",
  email: "Email",
  phone: "Phone",
  "billing_address.line1": "Address",
  "billing_address.city": "City",
  "billing_address.pincode": "PIN code",
  "billing_address.state_code": "State",
};

const TREATMENT_LABEL = Object.fromEntries(TREATMENTS.map((t) => [t.value, t.label]));

/** Clients from a CSV / Excel file (B.3): check first, then import, all or nothing. */
export function PartyImport({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  return (
    <SpreadsheetImport<ImportResult>
      title="Import clients"
      label="Clients file"
      noun="client"
      nouns="clients"
      hint="One client per row. Columns are found by name: name (needed), GSTIN, GST type (registered, composition, SEZ, unregistered, consumer or overseas: without it, a GSTIN means registered), state (a name like Kerala, or read from the GSTIN), PAN, email, phone, address, city, PIN code. Clients you already have are not imported twice."
      missingColumns="No header row found. The file needs at least a “Name” column."
      fieldLabels={FIELD_LABELS}
      samplePath="/api/v1/parties:import-sample"
      sampleName="clients-sample"
      upload={async (file, dryRun, key) =>
        unwrap(
          await api.POST("/api/v1/parties:import", {
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
        void queryClient.invalidateQueries({ queryKey: ["parties"] });
      }}
      onClose={onDone}
      preview={(result) => (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>GST</TableHead>
                <TableHead>GSTIN</TableHead>
                <TableHead>State</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.parties.slice(0, 100).map((p) => (
                <TableRow key={p.display_name}>
                  <TableCell>{p.display_name}</TableCell>
                  <TableCell>{TREATMENT_LABEL[p.gst_treatment] ?? p.gst_treatment}</TableCell>
                  <TableCell className="font-mono">{p.gstin}</TableCell>
                  <TableCell>{p.state_name}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {result.parties.length > 100 && (
            <p className="text-muted-foreground text-xs">
              Showing the first 100 of {result.parties.length}.
            </p>
          )}
        </>
      )}
    />
  );
}
