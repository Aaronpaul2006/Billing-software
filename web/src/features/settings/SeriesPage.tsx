import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Plus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field, TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import type { DocType } from "@/features/documents/api";
import { useRegistrations } from "@/features/projects/api";
import { applyServerErrors, ifMatch } from "@/lib/forms";

const PREFIX_SUGGESTIONS: Record<DocType, string> = {
  TAX_INVOICE: "INV/",
  BILL_OF_SUPPLY: "BOS/",
  PROFORMA: "PI/",
  QUOTATION: "QT/",
  CREDIT_NOTE: "CN/",
  DEBIT_NOTE: "DN/",
};

const formSchema = z
  .object({
    gst_registration_id: z.string().min(1, "Choose the registration."),
    doc_type: z.enum([
      "TAX_INVOICE",
      "BILL_OF_SUPPLY",
      "PROFORMA",
      "QUOTATION",
      "CREDIT_NOTE",
      "DEBIT_NOTE",
    ]),
    fy_start_year: z.string().regex(/^20\d{2}$/, "A year like 2026."),
    prefix: z.string().regex(/^[A-Za-z0-9/-]{0,10}$/, "Letters, digits, / and -, up to 10."),
    next_number: z.string().regex(/^[1-9]\d{0,7}$/, "A whole number from 1."),
    pad_width: z.string().regex(/^[1-8]$/, "1 to 8 digits."),
  })
  .refine((v) => v.prefix.length + Number(v.pad_width) <= 16, {
    path: ["prefix"],
    message: "Prefix plus digits may be at most 16 characters (GST rule).",
  });
type FormValues = z.infer<typeof formSchema>;

/** "INV/" + 7 padded to 4 -> "INV/0007". */
function sampleNumber(prefix: string, next: string, pad: string): string {
  const width = /^[1-8]$/.test(pad) ? Number(pad) : 4;
  return `${prefix}${(/^\d+$/.test(next) ? next : "1").padStart(width, "0")}`;
}

function AddSeries({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const registrations = useRegistrations();
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      gst_registration_id: "",
      doc_type: "TAX_INVOICE",
      fy_start_year: String(fyStartYear(new Date())),
      prefix: "INV/",
      next_number: "1",
      pad_width: "4",
    },
  });
  const { register, handleSubmit, formState, setValue, control } = form;
  const errors = formState.errors;
  const [prefix, next, pad, fy] = useWatch({
    control,
    name: ["prefix", "next_number", "pad_width", "fy_start_year"],
  });

  const save = useMutation({
    mutationFn: async (v: FormValues) =>
      unwrap(
        await api.POST("/api/v1/document-series", {
          body: {
            gst_registration_id: v.gst_registration_id,
            doc_type: v.doc_type,
            fy_start_year: Number(v.fy_start_year),
            prefix: v.prefix,
            next_number: Number(v.next_number),
            pad_width: Number(v.pad_width),
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document-series"] });
      onDone();
    },
    onError: (e) => {
      setError(
        applyServerErrors(e, form.setError, [
          "gst_registration_id",
          "doc_type",
          "fy_start_year",
          "prefix",
          "next_number",
          "pad_width",
        ]),
      );
    },
  });

  return (
    <form
      noValidate
      aria-label="New number series"
      className="bg-muted/40 mb-6 grid max-w-3xl gap-4 rounded-lg border p-4"
      onSubmit={(e) => {
        setError(null);
        void handleSubmit((v) => {
          save.mutate(v);
        })(e);
      }}
    >
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="series-reg" label="Registration" error={errors.gst_registration_id?.message}>
          {/* redrawn when the options arrive, so it shows the saved value (D.1) */}
          <NativeSelect
            key={registrations.data?.map((r) => r.id).join() ?? "loading"}
            id="series-reg"
            {...register("gst_registration_id")}
          >
            <option value="">–</option>
            {registrations.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.gstin ?? "Unregistered"} · {r.state_name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field id="series-type" label="Document type" error={errors.doc_type?.message}>
          <NativeSelect
            id="series-type"
            {...register("doc_type", {
              onChange: (e: { target: { value: DocType } }) => {
                setValue("prefix", PREFIX_SUGGESTIONS[e.target.value]);
              },
            })}
          >
            {Object.entries(DOC_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <TextField
          id="series-fy"
          label="Financial year starting"
          hint={`April ${fy} to March ${String(Number(fy) + 1)}.`}
          inputMode="numeric"
          maxLength={4}
          error={errors.fy_start_year?.message}
          registration={register("fy_start_year")}
        />
        <TextField
          id="series-prefix"
          label="Prefix"
          className="font-mono"
          error={errors.prefix?.message}
          registration={register("prefix")}
        />
        <TextField
          id="series-next"
          label="Next number"
          inputMode="numeric"
          hint="1 for a new year; higher to continue an existing book."
          error={errors.next_number?.message}
          registration={register("next_number")}
        />
        <TextField
          id="series-pad"
          label="Digits"
          inputMode="numeric"
          maxLength={1}
          error={errors.pad_width?.message}
          registration={register("pad_width")}
        />
      </div>
      <p className="text-sm">
        The next document will be numbered{" "}
        <strong className="font-mono">{sampleNumber(prefix, next, pad)}</strong>.
      </p>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Add series
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

type Series = components["schemas"]["DocumentSeries"];

function EditSeries({ series, onDone }: { series: Series; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [prefix, setPrefix] = useState(series.prefix);
  const [next, setNext] = useState(String(series.next_number));
  const [pad, setPad] = useState(String(series.pad_width));
  const [active, setActive] = useState(series.is_active);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/document-series/{series_id}", {
          params: { path: { series_id: series.id } },
          body: { prefix, next_number: Number(next), pad_width: Number(pad), is_active: active },
          headers: { "If-Match": ifMatch(series.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document-series"] });
      onDone();
    },
    onError: (e) => {
      setError(
        e instanceof ApiError && e.problem.errors?.length
          ? e.problem.errors.map((x) => x.message).join(" ")
          : e.message,
      );
    },
  });
  return (
    <form
      aria-label={`Edit series ${series.next_doc_number}`}
      className="grid gap-3 sm:grid-cols-4"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        if (!/^[1-9]\d{0,7}$/.test(next) || !/^[1-8]$/.test(pad)) {
          setError("Next number from 1; digits 1 to 8.");
          return;
        }
        save.mutate();
      }}
    >
      <Field id={`series-${series.id}-prefix`} label="Prefix">
        <Input
          id={`series-${series.id}-prefix`}
          className="font-mono"
          value={prefix}
          onChange={(e) => {
            setPrefix(e.target.value);
          }}
        />
      </Field>
      <Field id={`series-${series.id}-next`} label="Next number">
        <Input
          id={`series-${series.id}-next`}
          inputMode="numeric"
          value={next}
          onChange={(e) => {
            setNext(e.target.value);
          }}
        />
      </Field>
      <Field id={`series-${series.id}-pad`} label="Digits">
        <Input
          id={`series-${series.id}-pad`}
          inputMode="numeric"
          maxLength={1}
          value={pad}
          onChange={(e) => {
            setPad(e.target.value);
          }}
        />
      </Field>
      <label className="flex items-end gap-2 pb-2 text-sm">
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => {
            setActive(e.target.checked);
          }}
        />
        Active
      </label>
      <p className="text-sm sm:col-span-4">
        Next: <strong className="font-mono">{sampleNumber(prefix, next, pad)}</strong>. Prefix and
        digits lock once a document has used the series.
      </p>
      {error && <p className="text-destructive text-sm sm:col-span-4">{error}</p>}
      <div className="flex gap-2 sm:col-span-4">
        <Button type="submit" size="sm" disabled={save.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function SeriesPage() {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const registrations = useRegistrations();
  const series = useQuery({
    queryKey: ["document-series"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/document-series", {
          params: { query: { limit: 100, ordering: "-fy_start_year" } },
        }),
      ).results,
  });
  const regName = (id: string) =>
    registrations.data?.find((r) => r.id === id)?.gstin ?? "Unregistered";
  const rows = series.data ?? [];
  return (
    <>
      <PageHeader
        title="Number series"
        description="Documents get the next number of their series when issued: one series per registration, document type and financial year."
        actions={
          !adding && (
            <Button
              onClick={() => {
                setAdding(true);
              }}
            >
              <Plus aria-hidden /> Add series
            </Button>
          )
        }
      />
      {adding && (
        <AddSeries
          onDone={() => {
            setAdding(false);
          }}
        />
      )}
      {series.error ? (
        <ErrorState error={series.error} />
      ) : series.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No number series yet. Add one for each document type you issue (tax invoice first).
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document type</TableHead>
              <TableHead>Registration</TableHead>
              <TableHead>Financial year</TableHead>
              <TableHead>Next number</TableHead>
              <TableHead>
                <span className="sr-only">Status</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) =>
              editing === s.id ? (
                <TableRow key={s.id}>
                  <TableCell colSpan={5}>
                    <EditSeries
                      series={s}
                      onDone={() => {
                        setEditing(null);
                      }}
                    />
                  </TableCell>
                </TableRow>
              ) : (
                <TableRow key={s.id}>
                  <TableCell>{DOC_TYPE_LABELS[s.doc_type]}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {regName(s.gst_registration_id)}
                  </TableCell>
                  <TableCell>
                    {s.fy_start_year}–{String(s.fy_start_year + 1).slice(2)}
                  </TableCell>
                  <TableCell className="font-mono">{s.next_doc_number}</TableCell>
                  <TableCell className="text-right">
                    {!s.is_active && <Badge variant="secondary">Inactive</Badge>}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(s.id);
                      }}
                    >
                      Edit
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
