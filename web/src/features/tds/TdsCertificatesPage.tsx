import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { useConfirm } from "@/components/confirm-context";
import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fyStartYear } from "@/features/dashboard/periods";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";
import { cleanMoneyInput, formatInr, MONEY_INPUT } from "@/lib/money";
import { formatDate } from "@/lib/dates";

type Certificate = components["schemas"]["TdsCertificate"];
type CertificateWrite = components["schemas"]["TdsCertificateWrite"];

const QUARTERS = [
  { value: 1, label: "Q1 (Apr–Jun)" },
  { value: 2, label: "Q2 (Jul–Sep)" },
  { value: 3, label: "Q3 (Oct–Dec)" },
  { value: 4, label: "Q4 (Jan–Mar)" },
];

function problemText(e: unknown): string {
  if (e instanceof ApiError && e.code === "certificate_exists") {
    return "A certificate with this number from this TAN is already recorded.";
  }
  if (e instanceof ApiError && e.problem.errors?.length) {
    return e.problem.errors.map((x) => `${x.field ?? ""}: ${x.message}`).join(" ");
  }
  return errorMessage(e);
}

/** Adds a certificate, or corrects `existing` (a typo in the number, the amount...). */
function CertificateForm({
  fy,
  existing,
  onDone,
}: {
  fy: number;
  existing?: Certificate;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [party, setParty] = useState<PickedParty | null>(
    existing ? { id: existing.party_id, name: existing.party_name } : null,
  );
  const [tan, setTan] = useState(existing?.deductor_tan ?? "");
  const [quarter, setQuarter] = useState(existing?.quarter ?? 1);
  const [number, setNumber] = useState(existing?.certificate_number ?? "");
  const [date, setDate] = useState(existing?.certificate_date ?? "");
  const [credited, setCredited] = useState(existing?.amount_credited ?? "");
  const [tds, setTds] = useState(existing?.tds_amount ?? "");
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const idPrefix = existing ? `cert-${existing.id}` : "cert";

  const save = useMutation({
    mutationFn: async (body: CertificateWrite) =>
      existing
        ? unwrap(
            await api.PATCH("/api/v1/tds-certificates/{certificate_id}", {
              params: { path: { certificate_id: existing.id } },
              body,
              headers: { "If-Match": ifMatch(existing.version) },
            }),
          )
        : unwrap(
            await api.POST("/api/v1/tds-certificates", {
              body,
              headers: { "Idempotency-Key": key },
            }),
          ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tds-certificates"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "tds"] });
      onDone();
    },
    onError: (e) => {
      setError(problemText(e));
    },
  });

  return (
    <form
      aria-label={
        existing ? `Edit certificate ${existing.certificate_number}` : "New TDS certificate"
      }
      className="bg-muted/40 mb-6 grid max-w-4xl gap-4 rounded-lg border p-4 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        const amount = cleanMoneyInput(tds);
        if (!party) {
          setError("Choose the client who deducted the TDS.");
          return;
        }
        if (!/^[A-Za-z]{4}\d{5}[A-Za-z]$/.test(tan.trim())) {
          setError("Enter the client's TAN, e.g. BLRS12345E.");
          return;
        }
        if (!number.trim()) {
          setError("Enter the certificate number.");
          return;
        }
        if (!MONEY_INPUT.test(amount)) {
          setError("Enter the TDS amount on the certificate.");
          return;
        }
        save.mutate({
          party_id: party.id,
          deductor_tan: tan.trim().toUpperCase(),
          fy_start_year: existing?.fy_start_year ?? fy,
          quarter,
          certificate_number: number.trim(),
          certificate_date: date || null,
          amount_credited: cleanMoneyInput(credited) || null,
          tds_amount: amount,
        });
      }}
    >
      {error && (
        <Alert variant="destructive" className="sm:col-span-3">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Field id={`${idPrefix}-party`} label="Client">
        <PartyPicker id={`${idPrefix}-party`} value={party} onChange={setParty} />
      </Field>
      <Field id={`${idPrefix}-tan`} label="Client's TAN">
        <Input
          id={`${idPrefix}-tan`}
          className="font-mono uppercase"
          maxLength={10}
          value={tan}
          onChange={(e) => {
            setTan(e.target.value);
          }}
        />
      </Field>
      <Field id={`${idPrefix}-quarter`} label="Quarter">
        <NativeSelect
          id={`${idPrefix}-quarter`}
          value={quarter}
          onChange={(e) => {
            setQuarter(Number(e.target.value));
          }}
        >
          {QUARTERS.map((q) => (
            <option key={q.value} value={q.value}>
              {q.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id={`${idPrefix}-number`} label="Certificate number">
        <Input
          id={`${idPrefix}-number`}
          className="font-mono"
          value={number}
          onChange={(e) => {
            setNumber(e.target.value);
          }}
        />
      </Field>
      <Field id={`${idPrefix}-date`} label="Certificate date">
        <Input
          id={`${idPrefix}-date`}
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
          }}
        />
      </Field>
      <div />
      <Field
        id={`${idPrefix}-credited`}
        label="Amount paid / credited (₹)"
        hint="As the certificate states."
      >
        <Input
          id={`${idPrefix}-credited`}
          inputMode="decimal"
          value={credited}
          onChange={(e) => {
            setCredited(e.target.value);
          }}
        />
      </Field>
      <Field id={`${idPrefix}-tds`} label="TDS deducted (₹)">
        <Input
          id={`${idPrefix}-tds`}
          inputMode="decimal"
          value={tds}
          onChange={(e) => {
            setTds(e.target.value);
          }}
        />
      </Field>
      <div className="flex items-end gap-2">
        <Button type="submit" disabled={save.isPending}>
          {existing ? "Save" : "Add certificate"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Form 16A certificates from clients, reconciled in Reports → TDS reconciliation. */
export function TdsCertificatesPage() {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const current = fyStartYear(new Date());
  const [fy, setFy] = useState(current);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const certificates = useQuery({
    queryKey: ["tds-certificates", fy],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tds-certificates", {
          params: { query: { fy_start_year: fy, ordering: "quarter", limit: 100 } },
        }),
      ).results,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/tds-certificates/{certificate_id}", {
          params: { path: { certificate_id: id } },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tds-certificates"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "tds"] });
    },
    onError: (e) => {
      setNotice(problemText(e));
    },
  });

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/reports?tab=tds">
          <ArrowLeft aria-hidden /> TDS reconciliation
        </Link>
      </Button>
      <PageHeader
        title="TDS certificates"
        description="Form 16A from clients for the TDS (s.194C) they deducted from your bills."
        actions={
          <>
            <NativeSelect
              aria-label="Financial year"
              className="w-auto"
              value={fy}
              onChange={(e) => {
                setFy(Number(e.target.value));
              }}
            >
              {[current, current - 1, current - 2].map((y) => (
                <option key={y} value={y}>
                  FY {y}–{String(y + 1).slice(2)}
                </option>
              ))}
            </NativeSelect>
            {!adding && (
              <Button
                onClick={() => {
                  setAdding(true);
                }}
              >
                <Plus aria-hidden /> Add certificate
              </Button>
            )}
          </>
        }
      />
      {adding && (
        <CertificateForm
          fy={fy}
          onDone={() => {
            setAdding(false);
          }}
        />
      )}
      {notice && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      {certificates.error ? (
        <ErrorState error={certificates.error} />
      ) : !certificates.data ? (
        <Skeleton className="h-24 w-full" />
      ) : certificates.data.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No certificates recorded for this year.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Client</TableHead>
              <TableHead>Quarter</TableHead>
              <TableHead>Certificate</TableHead>
              <TableHead className="text-right">TDS</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {certificates.data.map((c) =>
              editing === c.id ? (
                <TableRow key={c.id}>
                  <TableCell colSpan={5} className="whitespace-normal">
                    <CertificateForm
                      fy={fy}
                      existing={c}
                      onDone={() => {
                        setEditing(null);
                      }}
                    />
                  </TableCell>
                </TableRow>
              ) : (
                <TableRow key={c.id}>
                  <TableCell>
                    {c.party_name}
                    <div className="text-muted-foreground font-mono text-xs">{c.deductor_tan}</div>
                  </TableCell>
                  <TableCell>Q{c.quarter}</TableCell>
                  <TableCell>
                    <span className="font-mono">{c.certificate_number}</span>
                    {c.certificate_date && (
                      <div className="text-muted-foreground text-xs">
                        {formatDate(c.certificate_date)}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatInr(c.tds_amount)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit certificate ${c.certificate_number}`}
                      onClick={() => {
                        setEditing(c.id);
                      }}
                    >
                      <Pencil aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete certificate ${c.certificate_number}`}
                      disabled={remove.isPending}
                      onClick={() => {
                        void confirm({
                          title: `Delete certificate ${c.certificate_number}?`,
                          description: "Only for a wrong entry: the record is removed for good.",
                          confirmLabel: "Delete certificate",
                          tone: "danger",
                        }).then((yes) => {
                          if (yes) remove.mutate(c.id);
                        });
                      }}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </TableCell>
                </TableRow>
              ),
            )}
          </TableBody>
        </Table>
      )}
    </>
  );
}
