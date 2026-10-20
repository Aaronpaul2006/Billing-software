import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Controller, useFieldArray, useForm, useWatch } from "react-hook-form";
import type { UseFormSetValue } from "react-hook-form";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field, TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { applyServerErrors, blankToNull, formPath, ifMatch } from "@/lib/forms";
import { STATES } from "@/lib/india";
import { cleanMoneyInput, formatInr, formatQty } from "@/lib/money";
import { useDebounced } from "@/lib/useDebounced";

import { DOC_TYPE_LABELS, documentKey, DRAFTABLE, useDocument } from "./api";
import type { Document, DraftableType } from "./api";
import { TotalsPanel } from "./TotalsPanel";

type DocumentWrite = components["schemas"]["DocumentWrite"];
type LineIn = components["schemas"]["LineIn"];
type BoqItem = components["schemas"]["BoqItem"];
type CatalogItem = components["schemas"]["CatalogItem"];

interface LineForm {
  item: string; // "", "boq:<id>" or "cat:<id>"
  description: string;
  sac_hsn: string;
  unit: string;
  quantity: string;
  rate: string;
  discount_amount: string;
  gst_rate: string;
}

interface FormValues {
  doc_type: DraftableType;
  party_id: string;
  project_id: string;
  doc_date: string;
  due_date: string;
  valid_until: string;
  is_ra_bill: boolean;
  round_to_rupee: boolean;
  notes: string;
  terms: string;
  lines: LineForm[];
}

const QTY = /^\d{1,11}(\.\d{1,3})?$/;
const RA_TYPES: ReadonlySet<string> = new Set(["TAX_INVOICE", "BILL_OF_SUPPLY", "PROFORMA"]);
const NOTE_TYPES: ReadonlySet<string> = new Set(["CREDIT_NOTE", "DEBIT_NOTE"]);
const EMPTY_LINE: LineForm = {
  item: "",
  description: "",
  sac_hsn: "",
  unit: "",
  quantity: "",
  rate: "",
  discount_amount: "",
  gst_rate: "",
};

function toForm(doc: Document | undefined, type: DraftableType): FormValues {
  if (!doc) {
    return {
      doc_type: type,
      party_id: "",
      project_id: "",
      doc_date: isoDate(new Date()),
      due_date: "",
      valid_until: "",
      is_ra_bill: false,
      round_to_rupee: false,
      notes: "",
      terms: "",
      lines: [{ ...EMPTY_LINE }],
    };
  }
  return {
    doc_type: doc.doc_type as DraftableType,
    party_id: doc.party_id,
    project_id: doc.project_id ?? "",
    doc_date: doc.doc_date,
    due_date: doc.due_date ?? "",
    valid_until: doc.valid_until ?? "",
    is_ra_bill: doc.is_ra_bill,
    round_to_rupee: doc.round_to_rupee,
    notes: doc.notes ?? "",
    terms: doc.terms ?? "",
    lines: doc.lines.map((l) => ({
      item: l.boq_item_id
        ? `boq:${l.boq_item_id}`
        : l.catalog_item_id
          ? `cat:${l.catalog_item_id}`
          : "",
      description: l.description,
      sac_hsn: l.sac_hsn ?? "",
      unit: l.unit ?? "",
      quantity: l.quantity,
      rate: l.rate,
      discount_amount: l.discount_amount === "0.00" ? "" : l.discount_amount,
      gst_rate: l.gst_rate,
    })),
  };
}

/** Lines for the API: blanks left out, so the server fills them from the BOQ / catalog item. */
function apiLine(l: LineForm): LineIn {
  const [kind, id] = l.item.split(":");
  const rate = cleanMoneyInput(l.rate);
  const discount = cleanMoneyInput(l.discount_amount);
  return {
    ...(kind === "boq" && id ? { boq_item_id: id } : {}),
    ...(kind === "cat" && id ? { catalog_item_id: id } : {}),
    ...(l.description.trim() ? { description: l.description.trim() } : {}),
    ...(l.sac_hsn.trim() ? { sac_hsn: l.sac_hsn.trim() } : {}),
    ...(l.unit.trim() ? { unit: l.unit.trim() } : {}),
    quantity: l.quantity.trim(),
    ...(rate ? { rate } : {}),
    ...(discount ? { discount_amount: discount } : {}),
    ...(l.gst_rate.trim() ? { gst_rate: l.gst_rate.trim() } : {}),
  };
}

function toApi(v: FormValues): DocumentWrite {
  const quotation = v.doc_type === "QUOTATION";
  return {
    doc_type: v.doc_type,
    party_id: v.party_id,
    project_id: blankToNull(v.project_id),
    doc_date: v.doc_date,
    due_date: quotation ? null : blankToNull(v.due_date),
    valid_until: quotation ? blankToNull(v.valid_until) : null,
    is_ra_bill: v.project_id !== "" && RA_TYPES.has(v.doc_type) && v.is_ra_bill,
    round_to_rupee: v.round_to_rupee,
    notes: blankToNull(v.notes),
    terms: blankToNull(v.terms),
    lines: v.lines.filter((l) => l.quantity.trim() !== "" || l.item !== "").map(apiLine),
  };
}

function useAllBoqItems(projectId: string) {
  return useQuery({
    queryKey: ["boq", projectId, "all"],
    queryFn: async () => {
      const items: BoqItem[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < 50; page += 1) {
        const result: { results: BoqItem[]; next_cursor: string | null } = unwrap(
          await api.GET("/api/v1/projects/{project_id}/boq-items", {
            params: {
              path: { project_id: projectId },
              query: { ordering: "sort_order", limit: 100, ...(cursor ? { cursor } : {}) },
            },
          }),
        );
        items.push(...result.results);
        cursor = result.next_cursor;
        if (!cursor) break;
      }
      return items;
    },
    enabled: projectId !== "",
    staleTime: 60_000,
  });
}

function fillFromItem(
  index: number,
  value: string,
  boq: BoqItem[],
  catalog: CatalogItem[],
  setValue: UseFormSetValue<FormValues>,
) {
  const [kind, id] = value.split(":");
  const set = (field: keyof LineForm, v: string | null | undefined) => {
    setValue(`lines.${index}.${field}`, v ?? "", { shouldDirty: true });
  };
  if (kind === "boq") {
    const b = boq.find((x) => x.id === id);
    if (!b) return;
    set("description", b.description);
    set("unit", b.unit);
    set("sac_hsn", b.sac_hsn);
    set("rate", b.rate);
    set("gst_rate", b.gst_rate);
  } else if (kind === "cat") {
    const c = catalog.find((x) => x.id === id);
    if (!c) return;
    set("description", c.description ?? c.name);
    set("unit", c.unit);
    set("sac_hsn", c.sac_hsn);
    set("rate", c.default_rate);
    set("gst_rate", c.gst_rate);
  }
}

function Editor({ doc }: { doc?: Document }) {
  const isNew = doc === undefined;
  const isNote = doc !== undefined && NOTE_TYPES.has(doc.doc_type);
  const [params] = useSearchParams();
  const requested = params.get("type") as DraftableType | null;
  const startType: DraftableType =
    requested && DRAFTABLE.includes(requested) ? requested : "TAX_INVOICE";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [party, setParty] = useState<PickedParty | null>(
    doc ? { id: doc.party_id, name: doc.party_name } : null,
  );
  const [message, setMessage] = useState<string | null>(null);
  const [key, setKey] = useState(newIdempotencyKey);

  const form = useForm<FormValues>({ defaultValues: toForm(doc, startType) });
  const { register, handleSubmit, control, setValue, setError, formState } = form;
  const errors = formState.errors;
  const lines = useFieldArray({ control, name: "lines" });
  const values = useWatch({ control }) as FormValues;

  const projects = useQuery({
    queryKey: ["projects", "of", values.party_id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects", {
          params: { query: { client_party_id: values.party_id, limit: 100, ordering: "code" } },
        }),
      ).results,
    enabled: values.party_id !== "",
  });
  const boq = useAllBoqItems(values.project_id);
  const catalog = useQuery({
    queryKey: ["catalog-items", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalog-items", {
          params: { query: { is_active: true, limit: 100 } },
        }),
      ).results,
    staleTime: 5 * 60_000,
  });

  // Live totals: the server's tax engine, asked again 400 ms after typing stops.
  const payload = useMemo(() => toApi(values), [values]);
  const ready =
    payload.party_id !== "" &&
    payload.lines !== undefined &&
    payload.lines.length > 0 &&
    payload.lines.every((l) => QTY.test(l.quantity) && Number(l.quantity) > 0);
  const debounced = useDebounced(JSON.stringify(payload), 400);
  const preview = useQuery({
    queryKey: ["preview-totals", debounced],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents:preview-totals", {
          body: JSON.parse(debounced) as DocumentWrite,
        }),
      ),
    enabled: ready && !isNote,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const previewErrors =
    preview.error instanceof ApiError ? (preview.error.problem.errors ?? []) : [];
  const lineError = (i: number) =>
    previewErrors
      .filter((e) => e.field?.startsWith(`lines[${String(i)}]`))
      .map(
        (e) =>
          `${
            formPath(e.field ?? "")
              .split(".")
              .pop() ?? ""
          }: ${e.message}`,
      )
      .join(" ");
  const headerErrors = previewErrors.filter((e) => !e.field?.startsWith("lines["));

  const save = useMutation({
    mutationFn: async (v: FormValues) => {
      const body = toApi(v);
      if (!doc) {
        return unwrap(
          await api.POST("/api/v1/documents", { body, headers: { "Idempotency-Key": key } }),
        );
      }
      // Notes keep their type, party and project; the rest may change while a draft.
      const patch = isNote
        ? {
            doc_date: body.doc_date,
            due_date: body.due_date,
            notes: body.notes,
            terms: body.terms,
            lines: body.lines,
          }
        : body;
      return unwrap(
        await api.PATCH("/api/v1/documents/{document_id}", {
          params: { path: { document_id: doc.id } },
          body: patch,
          headers: { "If-Match": ifMatch(doc.version) },
        }),
      );
    },
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      queryClient.setQueryData(documentKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void navigate(`/documents/${saved.id}`);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "stale_version") {
        setMessage("Someone else changed this draft. Reload the page to see their version.");
        return;
      }
      setMessage(
        applyServerErrors(e, setError, [
          "party_id",
          "project_id",
          "doc_type",
          "doc_date",
          "due_date",
          "valid_until",
          "is_ra_bill",
          "notes",
          "terms",
          "lines.*",
        ]),
      );
    },
  });

  const onSubmit = handleSubmit((v) => {
    setMessage(null);
    let ok = true;
    if (!v.party_id) {
      setError("party_id", { message: "Choose the client." });
      ok = false;
    }
    v.lines.forEach((l, i) => {
      if (!QTY.test(l.quantity.trim()) || Number(l.quantity) <= 0) {
        setError(`lines.${i}.quantity`, { message: "A quantity like 42.5." });
        ok = false;
      }
      if (l.rate.trim() && !/^\d{1,12}(\.\d{1,2})?$/.test(cleanMoneyInput(l.rate))) {
        setError(`lines.${i}.rate`, { message: "A rate like 6800 or 6800.50." });
        ok = false;
      }
    });
    if (ok) save.mutate(v);
  });

  const ra = values.is_ra_bill && values.project_id !== "" && RA_TYPES.has(values.doc_type);
  const boqItems = boq.data ?? [];
  const catalogItems = catalog.data ?? [];
  const title = isNew
    ? `New ${DOC_TYPE_LABELS[values.doc_type].toLowerCase()}`
    : `Edit draft ${DOC_TYPE_LABELS[doc.doc_type].toLowerCase()}`;

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to={doc ? `/documents/${doc.id}` : "/documents"}>
          <ArrowLeft aria-hidden /> {doc ? "Back to the draft" : "Invoices & quotes"}
        </Link>
      </Button>
      <PageHeader
        title={title}
        description="Amounts and tax are worked out by the server as you type."
      />
      <form noValidate className="grid gap-6" onSubmit={(e) => void onSubmit(e)}>
        {message && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <Field id="doc_type" label="Type" error={errors.doc_type?.message}>
              <NativeSelect id="doc_type" disabled={isNote} {...register("doc_type")}>
                {isNote ? (
                  <option value={doc.doc_type}>{DOC_TYPE_LABELS[doc.doc_type]}</option>
                ) : (
                  DRAFTABLE.map((t) => (
                    <option key={t} value={t}>
                      {DOC_TYPE_LABELS[t]}
                    </option>
                  ))
                )}
              </NativeSelect>
            </Field>
            <Field id="party" label="Client" error={errors.party_id?.message}>
              {isNote ? (
                <Input id="party" readOnly value={party?.name ?? ""} />
              ) : (
                <Controller
                  control={control}
                  name="party_id"
                  render={({ field }) => (
                    <PartyPicker
                      id="party"
                      value={party}
                      invalid={!!errors.party_id}
                      onChange={(picked) => {
                        setParty(picked);
                        field.onChange(picked?.id ?? "");
                        setValue("project_id", "");
                      }}
                    />
                  )}
                />
              )}
            </Field>
            <Field
              id="project_id"
              label="Project"
              error={errors.project_id?.message}
              hint="Its site state is the place of supply; its deductions apply."
            >
              <NativeSelect
                id="project_id"
                disabled={isNote || !values.party_id}
                {...register("project_id")}
              >
                <option value="">No project</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <TextField
              id="doc_date"
              label="Date"
              type="date"
              error={errors.doc_date?.message}
              registration={register("doc_date")}
            />
            {values.doc_type === "QUOTATION" ? (
              <TextField
                id="valid_until"
                label="Valid until"
                type="date"
                error={errors.valid_until?.message}
                registration={register("valid_until")}
              />
            ) : (
              <TextField
                id="due_date"
                label="Due date"
                type="date"
                error={errors.due_date?.message}
                registration={register("due_date")}
              />
            )}
            <div className="grid content-end gap-2 pb-1 text-sm">
              {values.project_id && RA_TYPES.has(values.doc_type) && !isNote && (
                <label className="flex items-center gap-2">
                  <input type="checkbox" {...register("is_ra_bill")} /> RA (running account) bill
                </label>
              )}
              <label className="flex items-center gap-2">
                <input type="checkbox" {...register("round_to_rupee")} /> Round the total to the
                rupee
              </label>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <h2>Lines</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {ra && (
              <p className="text-muted-foreground text-sm">
                RA bill: every line bills a BOQ item, once; the quantity is this bill&apos;s.
              </p>
            )}
            {lines.fields.map((field, i) => {
              const n = String(i);
              const lineErrors = errors.lines?.[i];
              const previewLine = preview.data?.lines[i];
              const problem = lineError(i);
              return (
                <fieldset
                  key={field.id}
                  aria-label={`Line ${String(i + 1)}`}
                  className="grid gap-3 rounded-lg border p-3 sm:grid-cols-12"
                >
                  <div className="grid gap-1 sm:col-span-4">
                    <label htmlFor={`line-${n}-item`} className="text-xs font-medium">
                      Item
                    </label>
                    <NativeSelect
                      id={`line-${n}-item`}
                      {...register(`lines.${i}.item`, {
                        onChange: (e: { target: { value: string } }) => {
                          fillFromItem(i, e.target.value, boqItems, catalogItems, setValue);
                        },
                      })}
                    >
                      <option value="">{ra ? "Choose a BOQ item" : "Free text"}</option>
                      {boqItems.length > 0 && (
                        <optgroup label="BOQ">
                          {boqItems.map((b) => (
                            <option key={b.id} value={`boq:${b.id}`}>
                              {b.item_code} · {b.description.slice(0, 60)}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {!ra && catalogItems.length > 0 && (
                        <optgroup label="Catalog">
                          {catalogItems.map((c) => (
                            <option key={c.id} value={`cat:${c.id}`}>
                              {c.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </NativeSelect>
                  </div>
                  <div className="grid gap-1 sm:col-span-8">
                    <label htmlFor={`line-${n}-description`} className="text-xs font-medium">
                      Description
                    </label>
                    <Input id={`line-${n}-description`} {...register(`lines.${i}.description`)} />
                  </div>
                  {(
                    [
                      ["quantity", ra ? "This bill qty" : "Quantity", "decimal", 2],
                      ["unit", "Unit", "text", 1],
                      ["rate", "Rate (₹)", "decimal", 2],
                      ["discount_amount", "Discount (₹)", "decimal", 2],
                      ["gst_rate", "GST %", "decimal", 1],
                      ["sac_hsn", "HSN/SAC", "numeric", 2],
                    ] as const
                  ).map(([name, label, mode, span]) => (
                    <div
                      key={name}
                      className={
                        span === 2 ? "grid gap-1 sm:col-span-2" : "grid gap-1 sm:col-span-1"
                      }
                    >
                      <label htmlFor={`line-${n}-${name}`} className="text-xs font-medium">
                        {label}
                      </label>
                      <Input
                        id={`line-${n}-${name}`}
                        inputMode={mode}
                        aria-invalid={!!lineErrors?.[name]}
                        {...register(`lines.${i}.${name}`)}
                      />
                      {lineErrors?.[name] && (
                        <span className="text-destructive text-xs">{lineErrors[name].message}</span>
                      )}
                    </div>
                  ))}
                  <div className="flex items-end justify-between gap-2 sm:col-span-2">
                    <div className="text-right text-sm">
                      {previewLine && (
                        <>
                          <div className="font-medium tabular-nums">
                            {formatInr(previewLine.line_total)}
                          </div>
                          {ra && previewLine.prev_cumulative_qty !== undefined && (
                            <div className="text-muted-foreground text-xs">
                              billed before {formatQty(previewLine.prev_cumulative_qty)}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove line ${String(i + 1)}`}
                      disabled={lines.fields.length === 1}
                      onClick={() => {
                        lines.remove(i);
                      }}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                  {problem && <p className="text-destructive text-sm sm:col-span-12">{problem}</p>}
                </fieldset>
              );
            })}
            <div>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  lines.append({ ...EMPTY_LINE });
                }}
              >
                <Plus aria-hidden /> Add line
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="flex flex-wrap justify-between gap-6">
          <div className="grid max-w-xl flex-1 gap-4">
            <Field id="notes" label="Notes">
              <textarea
                id="notes"
                rows={3}
                className="border-input rounded-md border bg-transparent px-3 py-2 text-sm"
                {...register("notes")}
              />
            </Field>
            <Field id="terms" label="Terms">
              <textarea
                id="terms"
                rows={3}
                className="border-input rounded-md border bg-transparent px-3 py-2 text-sm"
                {...register("terms")}
              />
            </Field>
          </div>
          <div className="grid content-start gap-2">
            {headerErrors.length > 0 && (
              <p className="text-destructive max-w-72 text-sm">
                {headerErrors.map((e) => e.message).join(" ")}
              </p>
            )}
            {preview.data ? (
              <>
                <p className="text-muted-foreground text-xs">
                  Place of supply{" "}
                  {STATES[preview.data.place_of_supply] ?? preview.data.place_of_supply}
                  {preview.isFetching ? " · updating…" : ""}
                </p>
                <TotalsPanel
                  totals={preview.data.totals}
                  intraState={preview.data.supply_type === "INTRA_STATE"}
                />
              </>
            ) : (
              <p className="text-muted-foreground max-w-72 text-sm">
                {isNote
                  ? "Totals are worked out when you save."
                  : "Choose the client and enter quantities to see the totals."}
              </p>
            )}
          </div>
        </div>

        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save draft
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to={doc ? `/documents/${doc.id}` : "/documents"}>Cancel</Link>
          </Button>
        </div>
      </form>
    </>
  );
}

export function NewDocumentPage() {
  return <Editor />;
}

export function EditDocumentPage() {
  const { documentId = "" } = useParams();
  const document = useDocument(documentId);
  if (document.error) return <ErrorState error={document.error} />;
  if (!document.data) return <Skeleton className="h-96 w-full" />;
  if (document.data.status !== "DRAFT") {
    return (
      <Alert>
        <AlertDescription>
          Only drafts can be edited.{" "}
          <Link to={`/documents/${documentId}`} className="underline">
            Back to the document
          </Link>
          ; issue a credit or debit note to change an issued invoice.
        </AlertDescription>
      </Alert>
    );
  }
  return <Editor doc={document.data} />;
}
