import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  FileUp,
  Keyboard,
  ListPlus,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Controller, useFieldArray, useForm, useWatch } from "react-hook-form";
import type { UseFormRegister } from "react-hook-form";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field, TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { useSession } from "@/auth/context";
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
import { placeName } from "@/lib/india";
import { cleanMoneyInput, formatInr, formatQty, toPaise } from "@/lib/money";
import { measuredTotal, rowQuantity } from "@/lib/quantity";
import type { MeasureRow } from "@/lib/quantity";
import { useDebounced } from "@/lib/useDebounced";

import { DOC_TYPE_LABELS, documentKey, DRAFTABLE, supplyNote, useDocument } from "./api";
import { ItemPicker } from "./ItemPicker";
import { catalogChoices, LINE_FIELD_LABELS, MAY_ADD_MASTERS } from "./items";
import { LinesImport } from "./LinesImport";
import type { ParsedLine } from "./LinesImport";
import type { PickedItem } from "./items";
import { AUTOSAVE } from "./autosave";
import { enterTarget, SHORTCUTS } from "./keyboard";
import { NewClientDialog, NewItemDialog } from "./QuickAdd";
import type { Document, DraftableType } from "./api";
import { usePrintSettings } from "@/features/settings/printSettings";

import { TotalsPanel } from "./TotalsPanel";

type DocumentWrite = components["schemas"]["DocumentWrite"];
type LineIn = components["schemas"]["LineIn"];
type BoqItem = components["schemas"]["BoqItem"];

interface LineForm {
  item: string; // "", "boq:<id>", "cat:<id>" or "var:<item id>:<variant id>"
  /** The chosen item's name, shown in the item box (not sent to the API). */
  item_label: string;
  description: string;
  sac_hsn: string;
  unit: string;
  quantity: string;
  rate: string;
  /** The discount as typed: rupees, or a percentage when discount_mode is "pct". */
  discount_amount: string;
  discount_mode: "amount" | "pct";
  gst_rate: string;
  /** B.9: a measurement sheet; when it has rows, the quantity is their total. */
  measurements: MeasureForm[];
}

interface MeasureForm extends MeasureRow {
  description: string;
}

const EMPTY_ROW: MeasureForm = {
  description: "",
  nos: "",
  length: "",
  breadth: "",
  height: "",
  deduct: false,
};

interface FormValues {
  doc_type: DraftableType;
  party_id: string;
  project_id: string;
  doc_date: string;
  due_date: string;
  valid_until: string;
  is_ra_bill: boolean;
  round_to_rupee: boolean;
  reverse_charge: boolean;
  /** SEZ / export: "yes" under the LUT, "no" charge IGST, "" the server's default. */
  lut: "" | "yes" | "no";
  notes: string;
  terms: string;
  lines: LineForm[];
}

const QTY = /^\d{1,11}(\.\d{1,3})?$/;
/** Roles that may see reports (the client's balance), docs/01-architecture.md §3. */
const REPORT_ROLES: ReadonlySet<string> = new Set(["OWNER", "ADMIN", "ACCOUNTANT", "VIEWER"]);
const RA_TYPES: ReadonlySet<string> = new Set(["TAX_INVOICE", "BILL_OF_SUPPLY", "PROFORMA"]);
const NOTE_TYPES: ReadonlySet<string> = new Set(["CREDIT_NOTE", "DEBIT_NOTE"]);
const EMPTY_LINE: LineForm = {
  item: "",
  item_label: "",
  description: "",
  sac_hsn: "",
  unit: "",
  quantity: "",
  rate: "",
  discount_amount: "",
  discount_mode: "amount",
  gst_rate: "",
  measurements: [],
};

function toForm(doc: Document | undefined, type: DraftableType, defaultTerms = ""): FormValues {
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
      reverse_charge: false,
      lut: "",
      notes: "",
      terms: defaultTerms, // the business's default terms (B.12), still editable
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
    reverse_charge: doc.reverse_charge,
    lut: doc.supply_category === "REGULAR" ? "" : doc.lut ? "yes" : "no",
    notes: doc.notes ?? "",
    terms: doc.terms ?? "",
    lines: doc.lines.map((l) => ({
      item: l.boq_item_id
        ? `boq:${l.boq_item_id}`
        : l.catalog_item_id && l.catalog_variant_id
          ? `var:${l.catalog_item_id}:${l.catalog_variant_id}`
          : l.catalog_item_id
            ? `cat:${l.catalog_item_id}`
            : "",
      item_label: l.boq_item_id || l.catalog_item_id ? l.description : "",
      description: l.description,
      sac_hsn: l.sac_hsn ?? "",
      unit: l.unit ?? "",
      quantity: l.quantity,
      rate: l.rate,
      discount_amount:
        l.discount_pct !== null
          ? l.discount_pct
          : l.discount_amount === "0.00"
            ? ""
            : l.discount_amount,
      discount_mode: l.discount_pct !== null ? "pct" : "amount",
      gst_rate: l.gst_rate,
      measurements: l.measurements.map((m) => ({
        description: m.description ?? "",
        nos: m.nos,
        length: m.length ?? "",
        breadth: m.breadth ?? "",
        height: m.height ?? "",
        deduct: m.deduct,
      })),
    })),
  };
}

/** Lines for the API: blanks left out, so the server fills them from the BOQ / catalog item. */
function apiLine(l: LineForm): LineIn {
  const [kind, id, variantId] = l.item.split(":");
  const rate = cleanMoneyInput(l.rate);
  const discount = cleanMoneyInput(l.discount_amount);
  return {
    ...(kind === "boq" && id ? { boq_item_id: id } : {}),
    ...(kind === "cat" && id ? { catalog_item_id: id } : {}),
    ...(kind === "var" && id && variantId
      ? { catalog_item_id: id, catalog_variant_id: variantId }
      : {}),
    ...(l.description.trim() ? { description: l.description.trim() } : {}),
    ...(l.sac_hsn.trim() ? { sac_hsn: l.sac_hsn.trim() } : {}),
    ...(l.unit.trim() ? { unit: l.unit.trim() } : {}),
    quantity: l.quantity.trim(),
    ...(rate ? { rate } : {}),
    ...(discount && l.discount_mode === "pct" ? { discount_pct: discount } : {}),
    ...(discount && l.discount_mode === "amount" ? { discount_amount: discount } : {}),
    ...(l.gst_rate.trim() ? { gst_rate: l.gst_rate.trim() } : {}),
    ...(l.measurements.length
      ? {
          measurements: l.measurements.map((m) => ({
            ...(m.description.trim() ? { description: m.description.trim() } : {}),
            nos: m.nos.trim() || "1",
            ...(m.length.trim() ? { length: m.length.trim() } : {}),
            ...(m.breadth.trim() ? { breadth: m.breadth.trim() } : {}),
            ...(m.height.trim() ? { height: m.height.trim() } : {}),
            deduct: m.deduct,
          })),
        }
      : {}),
  };
}

function fromParsed(l: ParsedLine): LineForm {
  return {
    ...EMPTY_LINE,
    description: l.description,
    sac_hsn: l.sac_hsn ?? "",
    unit: l.unit ?? "",
    quantity: l.quantity,
    rate: l.rate,
    discount_amount: l.discount_pct ?? l.discount_amount ?? "",
    discount_mode: l.discount_pct ? "pct" : "amount",
    gst_rate: l.gst_rate ?? "",
  };
}

function isEmptyLine(l: LineForm): boolean {
  return [l.item, l.description, l.quantity, l.rate, l.unit, l.sac_hsn, l.discount_amount].every(
    (x) => x.trim() === "",
  );
}

/** "2026-10-12" -> "12 Oct 2026". */
function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** "rows[3].rate" -> "Row 3 · Rate". */
function rowName(field: string | null | undefined): string {
  const m = /^rows\[(\d+)\]\.?(.*)$/.exec(field ?? "");
  if (!m) return "Pasted cells";
  const name = m[2] ?? "";
  return `Row ${m[1] ?? ""}${name ? ` · ${LINE_FIELD_LABELS[name] ?? name}` : ""}`;
}

/** A line with text but no quantity or item: not sent to the server yet (toApi leaves it out). */
function unsent(l: LineForm): boolean {
  return (
    l.quantity.trim() === "" &&
    l.item === "" &&
    [l.description, l.rate, l.unit, l.sac_hsn, l.discount_amount].some((x) => x.trim() !== "")
  );
}

/** Enough to save as a draft: a client, and at least one line, each with a quantity (and a valid rate). */
function saveable(body: DocumentWrite): boolean {
  return (
    body.party_id !== "" &&
    (body.lines ?? []).length > 0 && // not an empty draft the moment a client is chosen
    (body.lines ?? []).every(
      (l) =>
        QTY.test(l.quantity ?? "") &&
        Number(l.quantity) > 0 &&
        (l.rate === undefined || /^\d{1,12}(\.\d{1,2})?$/.test(l.rate)),
    )
  );
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
    reverse_charge: v.doc_type === "TAX_INVOICE" && v.reverse_charge,
    lut: v.lut === "" ? null : v.lut === "yes",
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

/** The rows of a line's measurement sheet (B.9); totals are exact (lib/quantity). */
function MeasurementSheet({
  line,
  rows,
  register,
  onChange,
}: {
  line: number;
  rows: MeasureForm[];
  register: UseFormRegister<FormValues>;
  onChange: (rows: MeasureForm[]) => void;
}) {
  const n = String(line + 1);
  const total = measuredTotal(rows);
  return (
    <div
      role="group"
      aria-label={`Measurement sheet of line ${n}`}
      className="bg-muted/40 grid gap-2 rounded-md border p-2 text-sm"
    >
      <div className="text-muted-foreground grid grid-cols-12 gap-2 text-xs font-medium">
        <span className="col-span-4">Description</span>
        <span className="col-span-1">Nos</span>
        <span className="col-span-1">Length</span>
        <span className="col-span-1">Breadth</span>
        <span className="col-span-1">Height</span>
        <span className="col-span-1">Deduct</span>
        <span className="col-span-2 text-right">Quantity</span>
      </div>
      {rows.map((row, j) => {
        const r = String(j + 1);
        const q = rowQuantity(row);
        const at = `lines.${line}.measurements.${j}` as const;
        return (
          <div key={j} className="grid grid-cols-12 items-center gap-2">
            <Input
              aria-label={`Row ${r} description`}
              className="col-span-4"
              {...register(`${at}.description`)}
            />
            {(["nos", "length", "breadth", "height"] as const).map((size) => (
              <Input
                key={size}
                aria-label={`Row ${r} ${size}`}
                inputMode="decimal"
                className="col-span-1"
                {...register(`${at}.${size}`)}
              />
            ))}
            <input
              type="checkbox"
              aria-label={`Row ${r} is a deduction`}
              className="col-span-1 justify-self-center"
              {...register(`${at}.deduct`)}
            />
            <span className="col-span-1 text-right tabular-nums">
              {q === null ? "—" : `${row.deduct ? "−" : ""}${formatQty(q)}`}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="col-span-1 justify-self-end"
              aria-label={`Remove row ${r} of line ${n}`}
              onClick={() => {
                onChange(rows.filter((_, k) => k !== j));
              }}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onChange([...rows, { ...EMPTY_ROW }]);
          }}
        >
          <Plus aria-hidden /> Add row
        </Button>
        <span className="font-medium tabular-nums">
          {total === null
            ? "Check the rows: each needs numbers like 10.5"
            : Number(total) <= 0
              ? "The rows add up to zero or less"
              : `Quantity: ${formatQty(total)}`}
        </span>
      </div>
    </div>
  );
}

type BulkField = "rate" | "discount_pct" | "gst_rate";

const BULK_FIELDS: { field: BulkField; label: string }[] = [
  { field: "rate", label: "Rate (₹)" },
  { field: "discount_pct", label: "Discount %" },
  { field: "gst_rate", label: "GST %" },
];

/** Change the rate, discount % or GST % of the selected lines at once (B.5). */
function BulkEdit({
  count,
  onApply,
  onClear,
}: {
  count: number;
  onApply: (field: BulkField, value: string) => void;
  onClear: () => void;
}) {
  const [field, setField] = useState<BulkField>("rate");
  const [value, setValue] = useState("");
  const valid = /^\d{1,12}(\.\d{1,2})?$/.test(cleanMoneyInput(value));
  return (
    <div
      role="group"
      aria-label="Change selected lines"
      className="bg-muted/40 flex flex-wrap items-end gap-2 rounded-lg border p-3 text-sm"
    >
      <span className="font-medium">
        {count} {count === 1 ? "line" : "lines"} selected:
      </span>
      <NativeSelect
        aria-label="What to change"
        className="w-auto"
        value={field}
        onChange={(e) => {
          setField(e.target.value as BulkField);
        }}
      >
        {BULK_FIELDS.map((f) => (
          <option key={f.field} value={f.field}>
            {f.label}
          </option>
        ))}
      </NativeSelect>
      <Input
        aria-label="New value"
        inputMode="decimal"
        className="w-32"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
        }}
      />
      <Button
        type="button"
        size="sm"
        disabled={!valid}
        onClick={() => {
          onApply(field, cleanMoneyInput(value));
          setValue("");
        }}
      >
        Apply to selected
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onClear}>
        Clear selection
      </Button>
    </div>
  );
}

function Editor({ doc, defaultTerms }: { doc?: Document; defaultTerms?: string }) {
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
  const { role } = useSession();
  const mayAddMasters = MAY_ADD_MASTERS.has(role);
  /** "New item" popup: for which line, starting with what was typed. */
  const [newItem, setNewItem] = useState<{ line: number; name: string } | null>(null);
  const [newClient, setNewClient] = useState(false);
  const [showKeys, setShowKeys] = useState(false);
  /** Lines chosen for a bulk edit, by their field id (stable across moves). */
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [importingLines, setImportingLines] = useState(false);
  const [pasteProblem, setPasteProblem] = useState<string[] | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  /** A new bill once it is saved: later saves update it (the page is not reloaded). */
  const [created, setCreated] = useState<Document | null>(null);
  const current = doc ?? created;
  /** After saving: "stay" (Ctrl+S) keeps the editor open; "open" shows the bill;
   * "review" (Ctrl+Enter) shows it with the final review open, ready to issue. */
  const after = useRef<"stay" | "open" | "review">("open");
  const formRef = useRef<HTMLFormElement>(null);
  const mayViewBalance = REPORT_ROLES.has(role);

  const form = useForm<FormValues>({ defaultValues: toForm(doc, startType, defaultTerms) });
  const { register, handleSubmit, control, setValue, setError, formState, getValues } = form;
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

  // Live totals: the server's tax engine, asked again 400 ms after typing stops.
  const payload = useMemo(() => toApi(values), [values]);
  const ready =
    payload.party_id !== "" &&
    payload.lines !== undefined &&
    payload.lines.length > 0 &&
    payload.lines.every((l) => QTY.test(l.quantity ?? "") && Number(l.quantity) > 0);
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
      .map((e) => {
        const name =
          formPath(e.field ?? "")
            .split(".")
            .pop() ?? "";
        return `${LINE_FIELD_LABELS[name] ?? name}: ${e.message}`;
      })
      .join(" ");
  const headerErrors = previewErrors.filter((e) => !e.field?.startsWith("lines["));

  /** Create the draft, or update it (If-Match): Save and autosave both use this. */
  const persist = async (body: DocumentWrite) => {
    if (!current) {
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
        params: { path: { document_id: current.id } },
        body: patch,
        headers: { "If-Match": ifMatch(current.version) },
      }),
    );
  };
  const stored = (saved: Document, sent: { json: string; form: string }) => {
    setKey(newIdempotencyKey());
    queryClient.setQueryData(documentKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    setSavedJson(sent.json);
    setSavedForm(sent.form);
    if (!doc) {
      // Keep editing in place (no reload, the cursor stays where it is); the address now
      // names the draft, so reloading the page opens it.
      setCreated(saved);
      // the server set the due date from the client's payment terms: keep it
      if (!getValues("due_date") && saved.due_date) {
        setValue("due_date", saved.due_date, { shouldDirty: true });
      }
      window.history.replaceState(window.history.state, "", `/documents/${saved.id}/edit`);
    }
  };

  const save = useMutation({
    mutationFn: async (v: FormValues) => persist(toApi(v)),
    onSuccess: (saved, v) => {
      stored(saved, { json: JSON.stringify(toApi(v)), form: JSON.stringify(v) });
      if (after.current === "stay") {
        const at = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
        setSavedAt(at);
      } else {
        const review = after.current === "review" && saved.status === "DRAFT";
        void navigate(`/documents/${saved.id}${review ? "?review=1" : ""}`);
      }
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
          "reverse_charge",
          "lut",
          "notes",
          "terms",
          "lines.*",
        ]),
      );
    },
  });

  // Autosave (B.6): what was last saved, compared with the form as it is now.
  const [savedJson, setSavedJson] = useState(() => JSON.stringify(toApi(toForm(doc, startType))));
  // Unsaved = the form differs from the last saved one (a line with only a description
  // is not sent yet, but it is still work to lose).
  const [savedForm, setSavedForm] = useState(() => JSON.stringify(toForm(doc, startType)));
  const [failedJson, setFailedJson] = useState<string | null>(null);
  const [autoProblem, setAutoProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const payloadJson = JSON.stringify(payload);
  const formJson = JSON.stringify(values);
  const unsaved = formJson !== savedForm || values.lines.some(unsent);
  const autosave = useMutation({
    mutationFn: async (sent: { json: string; form: string }) =>
      persist(JSON.parse(sent.json) as DocumentWrite),
    onSuccess: (saved, sent) => {
      stored(saved, sent);
      setAutoProblem(null);
      const at = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
      setSavedAt(at);
    },
    onError: (e, sent) => {
      setFailedJson(sent.json); // not again until something changes
      if (e instanceof ApiError && e.code === "stale_version") {
        setConflict(true);
        setMessage("Someone else changed this draft. Reload the page to see their version.");
      } else {
        setAutoProblem(e instanceof ApiError ? e.message : "Could not reach the server.");
      }
    },
  });
  const settledJson = useDebounced(payloadJson, AUTOSAVE.delayMs);
  const autosaveNow =
    AUTOSAVE.enabled &&
    settledJson === payloadJson && // typing has stopped
    settledJson !== savedJson &&
    settledJson !== failedJson &&
    !conflict &&
    !save.isPending &&
    !autosave.isPending &&
    saveable(JSON.parse(settledJson) as DocumentWrite);
  useEffect(() => {
    if (autosaveNow) autosave.mutate({ json: settledJson, form: formJson });
  }, [autosaveNow, settledJson, formJson, autosave]);

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

  /** Put a picked item on line `i`: its key, name and the values it fills in. */
  const pickItem = (i: number, picked: PickedItem | null) => {
    const set = (field: keyof LineForm, v: string | null | undefined) => {
      setValue(`lines.${i}.${field}`, v ?? "", { shouldDirty: true });
    };
    set("item", picked?.key ?? "");
    set("item_label", picked?.label ?? "");
    if (!picked) return; // cleared: the line keeps its text, as free text
    set("description", picked.fill.description);
    set("unit", picked.fill.unit);
    set("sac_hsn", picked.fill.sac_hsn);
    set("rate", picked.fill.rate);
    set("gst_rate", picked.fill.gst_rate);
  };

  /** Lines from a file or pasted cells: in place of an empty line at `at`, else after it. */
  const putLines = (parsed: ParsedLine[], at?: number) => {
    const forms = parsed.map(fromParsed);
    const current = getValues("lines");
    const index = at ?? current.length - 1;
    const here = current[index];
    const empty = here !== undefined && isEmptyLine(here);
    if (empty) {
      lines.remove(index);
      lines.insert(index, forms, { shouldFocus: false });
    } else {
      lines.insert(index + 1, forms, { shouldFocus: false });
    }
  };

  /** Several cells pasted from Excel into a line make lines; one value pastes as usual. */
  const onLinesPaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    const text = e.clipboardData.getData("text/plain");
    if (!/\t|\n.*\S/.test(text.trim())) return;
    const fieldset = (e.target as HTMLElement).closest("fieldset[data-line]");
    const all = Array.from(e.currentTarget.querySelectorAll("fieldset[data-line]"));
    const at = fieldset ? all.indexOf(fieldset) : undefined;
    e.preventDefault();
    setPasteProblem(null);
    void (async () => {
      try {
        const parsed = unwrap(await api.POST("/api/v1/documents:parse-lines", { body: { text } }));
        putLines(parsed.lines, at === -1 ? undefined : at);
      } catch (err) {
        const problem = err instanceof ApiError ? err.problem : null;
        setPasteProblem(
          problem?.errors?.length
            ? problem.errors.map((x) => `${rowName(x.field)}: ${x.message}`)
            : [problem?.detail ?? "Could not read the pasted cells."],
        );
      }
    })();
  };

  const addLine = (at?: number) => {
    const index = at ?? lines.fields.length;
    if (at === undefined) lines.append({ ...EMPTY_LINE }, { shouldFocus: false });
    else lines.insert(at, { ...EMPTY_LINE }, { shouldFocus: false });
    // the new line's item box, once React has put it on the page
    window.setTimeout(() => {
      document.getElementById(`line-${String(index)}-item`)?.focus();
    }, 0);
  };

  const submitWith = (mode: "stay" | "open" | "review") => {
    after.current = mode;
    void onSubmit();
  };
  const leave = () => {
    if (unsaved && !window.confirm("Leave this bill? Changes not saved will be lost.")) {
      return;
    }
    void navigate(current ? `/documents/${current.id}` : "/documents");
  };

  // Shortcuts anywhere on the page (popups and item lists handle their own Esc).
  const shortcut = useRef<(e: KeyboardEvent) => void>(() => undefined);
  const onShortcut = (e: KeyboardEvent) => {
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "s") {
      e.preventDefault();
      submitWith("stay");
    } else if (ctrl && e.key === "Enter") {
      e.preventDefault();
      submitWith("review");
    } else if (e.altKey && e.code === "KeyN") {
      e.preventDefault();
      addLine();
    } else if (e.altKey && (e.key === "/" || e.code === "Slash")) {
      e.preventDefault();
      setShowKeys((v) => !v);
    } else if (e.key === "Escape" && !newItem && !newClient) {
      e.preventDefault();
      if (showKeys) setShowKeys(false);
      else leave();
    }
  };
  useEffect(() => {
    shortcut.current = onShortcut; // the latest values, without re-adding the listener
  });
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      shortcut.current(e);
    };
    window.addEventListener("keydown", listener);
    return () => {
      window.removeEventListener("keydown", listener);
    };
  }, []);

  /** Enter moves on to the next box instead of sending the form. */
  const onFormKeyDown = (e: ReactKeyboardEvent<HTMLFormElement>) => {
    const el = e.target;
    if (e.key !== "Enter" || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    if (!(el instanceof HTMLInputElement || el instanceof HTMLSelectElement)) return;
    if (el.getAttribute("aria-expanded") === "true") return; // an open item list takes Enter
    if (!formRef.current) return;
    e.preventDefault();
    const target = enterTarget(formRef.current, el);
    if (target?.kind === "field") target.to.focus();
    else if (target?.kind === "new-line") addLine();
  };

  // B.9: a line with measurement rows takes their total as its quantity.
  useEffect(() => {
    values.lines.forEach((l, i) => {
      if (!l.measurements.length) return;
      const total = measuredTotal(l.measurements);
      if (total !== null && total !== l.quantity) {
        setValue(`lines.${i}.quantity`, total, { shouldDirty: true });
      }
    });
  }, [values.lines, setValue]);
  const [measuring, setMeasuring] = useState<Set<string>>(() => new Set());

  // A client chosen: their only project, or the one on their last bill.
  const projectFor = useRef<string | null>(null);
  const lastBill = useQuery({
    queryKey: ["documents", "last-for", values.party_id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents", {
          params: { query: { party_id: values.party_id, limit: 1 } },
        }),
      ).results[0] ?? null,
    enabled: values.party_id !== "" && !doc,
  });
  useEffect(() => {
    if (doc || !values.party_id || values.project_id || projectFor.current === values.party_id) {
      return;
    }
    const list = projects.data;
    if (!list || lastBill.isPending) return;
    projectFor.current = values.party_id;
    const last = lastBill.data?.project_id;
    const pick = list.length === 1 ? list[0]?.id : list.find((p) => p.id === last)?.id;
    if (pick) setValue("project_id", pick, { shouldDirty: true });
  }, [
    doc,
    values.party_id,
    values.project_id,
    projects.data,
    lastBill.isPending,
    lastBill.data,
    setValue,
  ]);

  const terms = useQuery({
    queryKey: ["parties", values.party_id, "terms"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}", {
          params: { path: { party_id: values.party_id } },
        }),
      ).payment_terms_days,
    enabled: values.party_id !== "" && !isNote,
  }).data;

  // B.8: the rate last charged to this client, per catalog item and variant
  const lastRates = useQuery({
    queryKey: ["parties", values.party_id, "last-rates"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}/last-rates", {
          params: { path: { party_id: values.party_id } },
        }),
      ).results,
    enabled: values.party_id !== "" && !isNote,
    staleTime: 60_000,
  });
  /** The client's last rate for this line's item, when it differs from the rate typed. */
  const lastRateFor = (line: LineForm | undefined) => {
    if (!line) return null;
    const [kind, id, variantId] = line.item.split(":");
    if ((kind !== "cat" && kind !== "var") || !id) return null;
    const last = lastRates.data?.find(
      (r) => r.catalog_item_id === id && (r.catalog_variant_id ?? undefined) === variantId,
    );
    if (!last) return null;
    return toPaise(cleanMoneyInput(line.rate)) === toPaise(last.rate) ? null : last;
  };

  const balance = useQuery({
    queryKey: ["statement", values.party_id, "now"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}/statement", {
          params: { path: { party_id: values.party_id } },
        }),
      ).closing_balance,
    enabled: values.party_id !== "" && mayViewBalance && !isNote,
    retry: false,
  });

  const ra = values.is_ra_bill && values.project_id !== "" && RA_TYPES.has(values.doc_type);
  const boqItems = boq.data ?? [];
  const title = current
    ? `Edit draft ${DOC_TYPE_LABELS[current.doc_type].toLowerCase()}`
    : `New ${DOC_TYPE_LABELS[values.doc_type].toLowerCase()}`;

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to={current ? `/documents/${current.id}` : "/documents"}>
          <ArrowLeft aria-hidden /> {doc ? "Back to the draft" : "Invoices & quotes"}
        </Link>
      </Button>
      <PageHeader
        title={title}
        description="Totals and tax update as you type. Enter moves to the next box."
        actions={
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-expanded={showKeys}
            onClick={() => {
              setShowKeys((v) => !v);
            }}
          >
            <Keyboard aria-hidden /> Keyboard shortcuts
          </Button>
        }
      />
      {showKeys && (
        <section
          aria-label="Keyboard shortcuts"
          className="bg-muted/40 mb-4 grid max-w-xl gap-1 rounded-lg border p-3 text-sm"
        >
          {SHORTCUTS.map((k) => (
            <div key={k.keys} className="flex gap-3">
              <kbd className="bg-background min-w-32 rounded border px-1.5 font-mono text-xs leading-6">
                {k.keys}
              </kbd>
              <span>{k.what}</span>
            </div>
          ))}
        </section>
      )}
      <form
        ref={formRef}
        noValidate
        className="grid gap-6"
        onKeyDown={onFormKeyDown}
        onSubmit={(e) => {
          after.current = "open";
          void onSubmit(e);
        }}
      >
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
                    <div className="grid gap-1">
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
                      {balance.data !== undefined && (
                        <p className="text-muted-foreground text-xs">
                          {balance.data.startsWith("-")
                            ? `Paid in advance: ${formatInr(balance.data.slice(1))}`
                            : balance.data === "0.00"
                              ? "Nothing to pay now."
                              : `Owes you now: ${formatInr(balance.data)}`}
                        </p>
                      )}
                      {mayAddMasters && (
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="h-auto justify-start p-0"
                          onClick={() => {
                            setNewClient(true);
                          }}
                        >
                          <Plus aria-hidden /> New client
                        </Button>
                      )}
                    </div>
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
                {...(terms !== null && terms !== undefined && !values.due_date && !current
                  ? {
                      hint: `Left empty: due ${String(terms)} days after the bill date (the client's payment terms).`,
                    }
                  : {})}
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
              {values.doc_type === "TAX_INVOICE" && (
                <label className="flex items-center gap-2">
                  <input type="checkbox" {...register("reverse_charge")} /> Reverse charge (the
                  client pays the GST)
                </label>
              )}
            </div>
            {!isNote && preview.data && preview.data.supply_category !== "REGULAR" && (
              <Field
                id="lut"
                label={preview.data.supply_category === "SEZ" ? "Supply to an SEZ unit" : "Export"}
                hint="Zero-rated: without IGST under your Letter of Undertaking, or with IGST."
              >
                <NativeSelect
                  id="lut"
                  value={values.lut || (preview.data.lut ? "yes" : "no")}
                  onChange={(e) => {
                    setValue("lut", e.target.value as "yes" | "no", { shouldDirty: true });
                  }}
                >
                  <option value="yes">Under the LUT, no IGST</option>
                  <option value="no">Charge IGST</option>
                </NativeSelect>
              </Field>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>
              <h2>Lines</h2>
            </CardTitle>
            {!importingLines && !ra && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setImportingLines(true);
                }}
              >
                <FileUp aria-hidden /> Import lines from Excel
              </Button>
            )}
          </CardHeader>
          <CardContent className="grid gap-3" onPaste={onLinesPaste}>
            {importingLines && (
              <LinesImport
                onLines={(parsed) => {
                  putLines(parsed);
                }}
                onDone={() => {
                  setImportingLines(false);
                }}
              />
            )}
            {pasteProblem && (
              <Alert variant="destructive">
                <AlertCircle aria-hidden />
                <AlertDescription>
                  The pasted rows were not added. Fix these and paste again:
                  <ul className="mt-1 grid gap-0.5">
                    {pasteProblem.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            {ra && (
              <p className="text-muted-foreground text-sm">
                RA bill: every line bills a BOQ item, once; the quantity is this bill&apos;s.
              </p>
            )}
            {selected.size > 0 && (
              <BulkEdit
                count={selected.size}
                onApply={(field, value) => {
                  lines.fields.forEach((f, i) => {
                    if (!selected.has(f.id)) return;
                    if (field === "discount_pct") {
                      setValue(`lines.${i}.discount_amount`, value, { shouldDirty: true });
                      setValue(`lines.${i}.discount_mode`, "pct", { shouldDirty: true });
                    } else {
                      setValue(`lines.${i}.${field}`, value, { shouldDirty: true });
                    }
                  });
                }}
                onClear={() => {
                  setSelected(new Set());
                }}
              />
            )}
            {lines.fields.length > 1 && (
              <label className="text-muted-foreground flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={selected.size === lines.fields.length}
                  onChange={(e) => {
                    setSelected(
                      e.target.checked ? new Set(lines.fields.map((f) => f.id)) : new Set(),
                    );
                  }}
                />
                Select all lines (to change their rate, discount or GST together)
              </label>
            )}
            {lines.fields.map((field, i) => {
              const n = String(i);
              const lineErrors = errors.lines?.[i];
              const previewLine = preview.data?.lines[i];
              const problem = lineError(i);
              const rows = values.lines[i]?.measurements ?? [];
              const box = (
                name: "quantity" | "unit" | "rate" | "gst_rate" | "sac_hsn",
                label: string,
                mode: "decimal" | "text" | "numeric",
                span: 1 | 2,
              ) => (
                <div
                  key={name}
                  className={span === 2 ? "grid gap-1 sm:col-span-2" : "grid gap-1 sm:col-span-1"}
                >
                  <label htmlFor={`line-${n}-${name}`} className="text-xs font-medium">
                    {label}
                  </label>
                  <Input
                    id={`line-${n}-${name}`}
                    inputMode={mode}
                    aria-invalid={!!lineErrors?.[name]}
                    readOnly={name === "quantity" && rows.length > 0}
                    title={
                      name === "quantity" && rows.length > 0
                        ? "The total of the measurement sheet below"
                        : undefined
                    }
                    {...register(`lines.${i}.${name}`)}
                  />
                  {lineErrors?.[name] && (
                    <span className="text-destructive text-xs">{lineErrors[name].message}</span>
                  )}
                </div>
              );
              return (
                <fieldset
                  key={field.id}
                  data-line
                  aria-label={`Line ${String(i + 1)}`}
                  className="grid gap-3 rounded-lg border p-3 sm:grid-cols-12"
                >
                  <label className="text-muted-foreground flex items-center gap-2 text-xs sm:col-span-12">
                    <input
                      type="checkbox"
                      checked={selected.has(field.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(field.id);
                        else next.delete(field.id);
                        setSelected(next);
                      }}
                    />
                    Select line {i + 1}
                  </label>
                  <div className="grid gap-1 sm:col-span-4">
                    <label htmlFor={`line-${n}-item`} className="text-xs font-medium">
                      Item
                    </label>
                    <ItemPicker
                      id={`line-${n}-item`}
                      label={values.lines[i]?.item_label ?? ""}
                      boq={boqItems}
                      boqOnly={ra}
                      onPick={(picked) => {
                        pickItem(i, picked);
                      }}
                      onCreate={
                        mayAddMasters
                          ? (name) => {
                              setNewItem({ line: i, name });
                            }
                          : undefined
                      }
                    />
                  </div>
                  <div className="grid gap-1 sm:col-span-8">
                    <label htmlFor={`line-${n}-description`} className="text-xs font-medium">
                      Description
                    </label>
                    <Input id={`line-${n}-description`} {...register(`lines.${i}.description`)} />
                  </div>
                  {box("quantity", ra ? "This bill qty" : "Quantity", "decimal", 2)}
                  {box("unit", "Unit", "text", 1)}
                  {box("rate", "Rate (₹)", "decimal", 2)}
                  {(() => {
                    const last = lastRateFor(values.lines[i]);
                    if (!last) return null;
                    return (
                      <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs sm:order-last sm:col-span-12">
                        Last charged to this client: {formatInr(last.rate)} on{" "}
                        {last.doc_number ?? "a bill"} ({shortDate(last.doc_date)})
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="h-auto p-0 text-xs"
                          onClick={() => {
                            setValue(`lines.${i}.rate`, last.rate, { shouldDirty: true });
                          }}
                        >
                          Use {formatInr(last.rate)}
                        </Button>
                      </p>
                    );
                  })()}
                  <div className="grid gap-1 sm:col-span-2">
                    <label htmlFor={`line-${n}-discount_amount`} className="text-xs font-medium">
                      Discount
                    </label>
                    <div className="flex gap-1">
                      <Input
                        id={`line-${n}-discount_amount`}
                        inputMode="decimal"
                        aria-invalid={!!(lineErrors?.discount_amount ?? lineErrors?.discount_mode)}
                        {...register(`lines.${i}.discount_amount`)}
                      />
                      <NativeSelect
                        aria-label={`Discount of line ${String(i + 1)} in`}
                        className="w-16"
                        {...register(`lines.${i}.discount_mode`)}
                      >
                        <option value="amount">₹</option>
                        <option value="pct">%</option>
                      </NativeSelect>
                    </div>
                    {lineErrors?.discount_amount && (
                      <span className="text-destructive text-xs">
                        {lineErrors.discount_amount.message}
                      </span>
                    )}
                  </div>
                  {box("gst_rate", "GST %", "decimal", 1)}
                  {box("sac_hsn", "HSN/SAC", "numeric", 2)}
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
                    <div className="flex">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Move line ${String(i + 1)} up`}
                        disabled={i === 0}
                        onClick={() => {
                          lines.move(i, i - 1);
                        }}
                      >
                        <ArrowUp aria-hidden />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Move line ${String(i + 1)} down`}
                        disabled={i === lines.fields.length - 1}
                        onClick={() => {
                          lines.move(i, i + 1);
                        }}
                      >
                        <ArrowDown aria-hidden />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Insert a line below line ${String(i + 1)}`}
                        onClick={() => {
                          addLine(i + 1);
                        }}
                      >
                        <ListPlus aria-hidden />
                      </Button>
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
                  </div>
                  <div className="sm:order-last sm:col-span-12">
                    {rows.length === 0 && !measuring.has(field.id) ? (
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        className="h-auto p-0 text-xs"
                        onClick={() => {
                          setMeasuring(new Set(measuring).add(field.id));
                          setValue(`lines.${i}.measurements`, [{ ...EMPTY_ROW }], {
                            shouldDirty: true,
                          });
                        }}
                      >
                        Add a measurement sheet (number × length × breadth × height)
                      </Button>
                    ) : (
                      <MeasurementSheet
                        line={i}
                        rows={rows}
                        register={register}
                        onChange={(next) => {
                          setValue(`lines.${i}.measurements`, next, { shouldDirty: true });
                        }}
                      />
                    )}
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
                  addLine();
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
                  Place of supply {placeName(preview.data.place_of_supply)}
                  {preview.isFetching ? " · updating…" : ""}
                </p>
                {supplyNote(preview.data) && (
                  <p className="max-w-72 text-sm font-medium">{supplyNote(preview.data)}</p>
                )}
                <TotalsPanel
                  totals={preview.data.totals}
                  intraState={preview.data.supply_type === "INTRA_STATE"}
                  reverseCharge={preview.data.reverse_charge}
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

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={save.isPending}>
            Save draft
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={save.isPending}
            onClick={() => {
              submitWith("stay");
            }}
          >
            Save and keep working
          </Button>
          <Button type="button" variant="ghost" onClick={leave}>
            Cancel
          </Button>
          <span role="status" className="text-muted-foreground flex items-center gap-1 text-sm">
            {autosave.isPending ? (
              "Saving…"
            ) : conflict ? null : unsaved ? (
              autoProblem ? (
                `Not saved: ${autoProblem}`
              ) : !saveable(payload) ? (
                "Not saved yet: choose the client and fill in each line's quantity."
              ) : null
            ) : savedAt ? (
              <>
                <CheckCircle2 className="size-4" aria-hidden /> Saved at {savedAt}
              </>
            ) : null}
          </span>
        </div>
      </form>
      {newItem && (
        <NewItemDialog
          name={newItem.name}
          onClose={() => {
            setNewItem(null);
          }}
          onCreated={(item) => {
            pickItem(newItem.line, catalogChoices([item])[0] ?? null);
            setNewItem(null);
          }}
        />
      )}
      {newClient && (
        <NewClientDialog
          onClose={() => {
            setNewClient(false);
          }}
          onCreated={(created) => {
            setParty({ id: created.id, name: created.display_name });
            setValue("party_id", created.id, { shouldDirty: true });
            setValue("project_id", "");
            setNewClient(false);
          }}
        />
      )}
    </>
  );
}

export function NewDocumentPage() {
  const settings = usePrintSettings();
  // Wait for the default terms, but never let a failed lookup stop billing.
  if (settings.isPending) return <Skeleton className="h-96 w-full" />;
  return <Editor defaultTerms={settings.data?.default_terms ?? ""} />;
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
