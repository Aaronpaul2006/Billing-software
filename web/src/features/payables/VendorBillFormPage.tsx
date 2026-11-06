import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Lightbulb } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { SaveBar } from "@/components/SaveBar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { CATEGORY_LABELS } from "@/features/expenses/labels";
import type { Category } from "@/features/expenses/labels";
import { useDebounced } from "@/lib/useDebounced";
import { ifMatch } from "@/lib/forms";
import { cleanMoneyInput, formatInr, MONEY_INPUT, sumMoney } from "@/lib/money";

import { useVendorBill, vendorBillKey } from "./api";
import type { VendorBill } from "./api";

const RATE = /^\d{1,2}(\.\d{1,2})?$/;

function problems(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !e.problem.errors) return {};
  return Object.fromEntries(e.problem.errors.map((x) => [x.field ?? "", x.message]));
}

/** What the server suggests for TDS on this bill, with a button to use it. */
function TdsHint({
  vendorId,
  category,
  taxable,
  billDate,
  billId,
  onUse,
}: {
  vendorId: string;
  category: Category;
  taxable: string;
  billDate: string;
  billId?: string;
  onUse: (section: string, rate: string) => void;
}) {
  const value = useDebounced(MONEY_INPUT.test(taxable) ? taxable : "", 400);
  const hint = useQuery({
    queryKey: ["tds-suggestion", vendorId, category, value, billDate, billId],
    enabled: vendorId !== "" && value !== "" && billDate !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/vendor-bills/tds-suggestion", {
          params: {
            query: {
              vendor_party_id: vendorId,
              category,
              taxable_value: value,
              bill_date: billDate,
              ...(billId ? { vendor_bill_id: billId } : {}),
            },
          },
        }),
      ),
  });
  if (!hint.data) return null;
  const s = hint.data;
  return (
    <div
      role="status"
      className="border-info-border bg-info-soft flex flex-wrap items-start gap-3 rounded-md border p-3 text-sm"
    >
      <Lightbulb className="text-info mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-48 flex-1">
        <p className="font-medium">
          {s.section
            ? `Suggested TDS: ${s.section} at ${s.rate} % = ${formatInr(s.amount)}`
            : "No TDS suggested"}
        </p>
        <p className="text-muted-foreground">{s.reason}</p>
      </div>
      {s.section && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            onUse(s.section ?? "", s.rate);
          }}
        >
          Use this
        </Button>
      )}
    </div>
  );
}

function BillForm({ bill }: { bill?: VendorBill }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [vendor, setVendor] = useState<PickedParty | null>(
    bill ? { id: bill.vendor_party_id, name: bill.vendor_name } : null,
  );
  const [projectId, setProjectId] = useState(bill?.project_id ?? "");
  const [number, setNumber] = useState(bill?.bill_number ?? "");
  const [billDate, setBillDate] = useState(bill?.bill_date ?? isoDate(new Date()));
  const [dueDate, setDueDate] = useState(bill?.due_date ?? "");
  const [category, setCategory] = useState<Category>(bill?.category ?? "SUBCONTRACT");
  const [description, setDescription] = useState(bill?.description ?? "");
  const [taxable, setTaxable] = useState(bill?.taxable_value ?? "");
  const [gst, setGst] = useState(bill?.gst_amount ?? "0.00");
  const [itc, setItc] = useState(bill?.itc_eligible ?? false);
  const [section, setSection] = useState(bill?.tds_section ?? "");
  const [rate, setRate] = useState(bill?.tds_section ? bill.tds_rate : "");
  const [key, setKey] = useState(newIdempotencyKey);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["projects", "active-list"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects", { params: { query: { limit: 100, ordering: "code" } } }),
      ).results,
    staleTime: 60_000,
  });

  const cleanTaxable = cleanMoneyInput(taxable);
  const cleanGst = cleanMoneyInput(gst || "0");
  const total = sumMoney([cleanTaxable || "0", cleanGst || "0"]);

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        vendor_party_id: vendor?.id ?? "",
        project_id: projectId || null,
        bill_number: number.trim(),
        bill_date: billDate,
        due_date: dueDate || null,
        category,
        description: description.trim(),
        taxable_value: cleanTaxable,
        gst_amount: cleanGst || "0.00",
        itc_eligible: itc,
        tds_section: section.trim().toUpperCase() || null,
        tds_rate: section.trim() ? rate || "0" : null,
      };
      if (!bill) {
        return unwrap(
          await api.POST("/api/v1/vendor-bills", { body, headers: { "Idempotency-Key": key } }),
        );
      }
      return unwrap(
        await api.PATCH("/api/v1/vendor-bills/{bill_id}", {
          params: { path: { bill_id: bill.id } },
          body,
          headers: { "If-Match": ifMatch(bill.version) },
        }),
      );
    },
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      queryClient.setQueryData(vendorBillKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      void navigate(`/vendor-bills/${saved.id}`);
    },
    onError: (e) => {
      setErrors(problems(e));
      setMessage(
        e instanceof ApiError && e.code === "stale_version"
          ? "Someone else changed this bill. Reload the page to see their version."
          : e instanceof ApiError && e.problem.errors?.length
            ? "Check the boxes marked below."
            : e.message,
      );
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    if (!vendor) local.vendor_party_id = "Choose the vendor.";
    if (!number.trim()) local.bill_number = "Enter the vendor's bill number.";
    if (!description.trim()) local.description = "Say what the bill is for.";
    if (!MONEY_INPUT.test(cleanTaxable)) local.taxable_value = "Enter the amount before GST.";
    if (gst && !MONEY_INPUT.test(cleanGst)) local.gst_amount = "Enter the GST, or 0.";
    if (section.trim() && !RATE.test(rate)) local.tds_rate = "Enter the TDS rate, e.g. 1 or 2.";
    setErrors(local);
    setMessage(Object.keys(local).length ? "Check the boxes marked below." : null);
    if (Object.keys(local).length === 0) save.mutate();
  };

  return (
    <form
      noValidate
      aria-label={bill ? "Edit vendor bill" : "Record vendor bill"}
      className="grid max-w-3xl gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {message && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field id="vendor" label="Vendor" error={errors.vendor_party_id}>
            <PartyPicker
              id="vendor"
              role="vendor"
              value={vendor}
              invalid={!!errors.vendor_party_id}
              onChange={setVendor}
            />
          </Field>
          <Field id="bill-number" label="Their bill number" error={errors.bill_number}>
            <Input
              id="bill-number"
              value={number}
              aria-invalid={!!errors.bill_number}
              onChange={(e) => {
                setNumber(e.target.value);
              }}
            />
          </Field>
          <Field id="bill-date" label="Bill date" error={errors.bill_date}>
            <Input
              id="bill-date"
              type="date"
              value={billDate}
              onChange={(e) => {
                setBillDate(e.target.value);
              }}
            />
          </Field>
          <Field id="due-date" label="Pay by (optional)" error={errors.due_date}>
            <Input
              id="due-date"
              type="date"
              value={dueDate}
              onChange={(e) => {
                setDueDate(e.target.value);
              }}
            />
          </Field>
          <Field id="category" label="Kind of bill">
            <NativeSelect
              id="category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value as Category);
              }}
            >
              {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id="project" label="Project">
            <NativeSelect
              key={projects.data?.map((p) => p.id).join() ?? "loading"}
              id="project"
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
              }}
            >
              <option value="">Office (no project)</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <div className="sm:col-span-2">
            <Field id="description" label="What it is for" error={errors.description}>
              <Input
                id="description"
                value={description}
                aria-invalid={!!errors.description}
                onChange={(e) => {
                  setDescription(e.target.value);
                }}
              />
            </Field>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field id="taxable" label="Amount before GST (₹)" error={errors.taxable_value}>
            <Input
              id="taxable"
              inputMode="decimal"
              value={taxable}
              aria-invalid={!!errors.taxable_value}
              onChange={(e) => {
                setTaxable(e.target.value);
              }}
            />
          </Field>
          <Field id="gst" label="GST (₹)" error={errors.gst_amount}>
            <Input
              id="gst"
              inputMode="decimal"
              value={gst}
              aria-invalid={!!errors.gst_amount}
              onChange={(e) => {
                setGst(e.target.value);
              }}
            />
          </Field>
          <label className="flex min-h-6 items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={itc}
              onChange={(e) => {
                setItc(e.target.checked);
              }}
            />
            We can claim this GST (input tax credit)
          </label>
          <div className="sm:col-span-2">
            {vendor && (
              <TdsHint
                vendorId={vendor.id}
                category={category}
                taxable={cleanTaxable}
                billDate={billDate}
                billId={bill?.id}
                onUse={(s, r) => {
                  setSection(s);
                  setRate(r);
                }}
              />
            )}
          </div>
          <Field
            id="tds-section"
            label="TDS section (empty: no TDS)"
            hint="e.g. 194C for contractors and subcontractors"
            error={errors.tds_section}
          >
            <Input
              id="tds-section"
              value={section}
              onChange={(e) => {
                setSection(e.target.value);
              }}
            />
          </Field>
          <Field id="tds-rate" label="TDS rate (%)" error={errors.tds_rate}>
            <Input
              id="tds-rate"
              inputMode="decimal"
              value={rate}
              disabled={!section.trim()}
              onChange={(e) => {
                setRate(e.target.value);
              }}
            />
          </Field>
        </CardContent>
      </Card>
      <SaveBar
        status={
          total && total !== "0.00" ? (
            <span className="text-foreground font-semibold">Bill total {formatInr(total)}</span>
          ) : undefined
        }
      >
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            void navigate(bill ? `/vendor-bills/${bill.id}` : "/vendor-bills");
          }}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {bill ? "Save changes" : "Record bill"}
        </Button>
      </SaveBar>
    </form>
  );
}

export function VendorBillFormPage() {
  const { billId } = useParams();
  const bill = useVendorBill(billId);
  const editing = billId !== undefined;
  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Vendor bills", to: "/vendor-bills" },
          ...(editing && bill.data
            ? [
                { label: bill.data.bill_number, to: `/vendor-bills/${bill.data.id}` },
                { label: "Edit" },
              ]
            : [{ label: "New" }]),
        ]}
      />
      <PageHeader
        title={editing ? "Edit vendor bill" : "Record a vendor bill"}
        description="As the vendor's bill says. The TDS we deduct and what we pay are worked out for you."
      />
      {editing && bill.error ? (
        <ErrorState error={bill.error} />
      ) : editing && !bill.data ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <BillForm bill={bill.data} />
      )}
    </>
  );
}
