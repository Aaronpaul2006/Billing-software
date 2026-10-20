import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field, TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { MODE_LABELS } from "@/features/payments/modes";
import { applyServerErrors, blankToNull, ifMatch } from "@/lib/forms";
import { cleanMoneyInput, formatInr, sumMoney } from "@/lib/money";

import { CATEGORY_LABELS } from "./labels";

type Expense = components["schemas"]["Expense"];
type ExpenseWrite = components["schemas"]["ExpenseWrite"];
type Mode = components["schemas"]["PaymentModeEnum"];

const money = (message: string) =>
  z.string().refine((v) => /^(\d{1,12}(\.\d{1,2})?)?$/.test(cleanMoneyInput(v)), message);

const formSchema = z.object({
  category: z.enum([
    "MATERIAL",
    "LABOUR",
    "SUBCONTRACT",
    "EQUIPMENT",
    "TRANSPORT",
    "SITE_OVERHEAD",
    "OFFICE",
    "OTHER",
  ]),
  expense_date: z.string().min(1, "Enter the date."),
  description: z.string().trim().min(1, "Describe the expense.").max(1000),
  project_id: z.string(),
  vendor_party_id: z.string(),
  vendor_bill_number: z.string().max(50),
  taxable_value: money("An amount like 38000.").refine((v) => v.trim() !== "", "Enter the amount."),
  gst_amount: money("An amount like 10640."),
  itc_eligible: z.boolean(),
  amount_paid: money("An amount like 20000."),
  payment_mode: z.string(),
});
type FormValues = z.infer<typeof formSchema>;

const FIELDS = [
  "category",
  "expense_date",
  "description",
  "project_id",
  "vendor_party_id",
  "vendor_bill_number",
  "taxable_value",
  "gst_amount",
  "itc_eligible",
  "amount_paid",
  "payment_mode",
] as const;

function toForm(x: Expense | undefined): FormValues {
  return {
    category: x?.category ?? "MATERIAL",
    expense_date: x?.expense_date ?? isoDate(new Date()),
    description: x?.description ?? "",
    project_id: x?.project_id ?? "",
    vendor_party_id: x?.vendor_party_id ?? "",
    vendor_bill_number: x?.vendor_bill_number ?? "",
    taxable_value: x?.taxable_value ?? "",
    gst_amount: x && x.gst_amount !== "0.00" ? x.gst_amount : "",
    itc_eligible: x?.itc_eligible ?? false,
    amount_paid: x && x.amount_paid !== "0.00" ? x.amount_paid : "",
    payment_mode: x?.payment_mode ?? "",
  };
}

function toApi(v: FormValues): ExpenseWrite {
  const paid = cleanMoneyInput(v.amount_paid);
  return {
    category: v.category,
    expense_date: v.expense_date,
    description: v.description.trim(),
    project_id: blankToNull(v.project_id),
    vendor_party_id: blankToNull(v.vendor_party_id),
    vendor_bill_number: blankToNull(v.vendor_bill_number),
    taxable_value: cleanMoneyInput(v.taxable_value),
    gst_amount: cleanMoneyInput(v.gst_amount) || "0",
    itc_eligible: v.itc_eligible,
    amount_paid: paid || "0",
    payment_mode: paid && paid !== "0" ? ((v.payment_mode || null) as Mode | null) : null,
  };
}

function ExpenseForm({ expense }: { expense?: Expense }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [vendor, setVendor] = useState<PickedParty | null>(
    expense?.vendor_party_id
      ? { id: expense.vendor_party_id, name: expense.vendor_name ?? "" }
      : null,
  );
  const [message, setMessage] = useState<string | null>(null);
  const [key, setKey] = useState(newIdempotencyKey);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: toForm(expense),
  });
  const { register, handleSubmit, control, setError, formState, reset } = form;
  const errors = formState.errors;
  const [taxable, gst, paid] = useWatch({
    control,
    name: ["taxable_value", "gst_amount", "amount_paid"],
  });
  const total = sumMoney([taxable, gst]); // shown while typing; the server stores its own
  const voided = expense?.status === "VOIDED";
  useEffect(() => {
    if (expense) reset(toForm(expense));
  }, [expense, reset]);

  const projects = useQuery({
    queryKey: ["projects", "active-list"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects", { params: { query: { limit: 100, ordering: "code" } } }),
      ).results,
    staleTime: 60_000,
  });

  const save = useMutation({
    mutationFn: async (v: FormValues) => {
      const body = toApi(v);
      if (!expense) {
        return unwrap(
          await api.POST("/api/v1/expenses", { body, headers: { "Idempotency-Key": key } }),
        );
      }
      return unwrap(
        await api.PATCH("/api/v1/expenses/{expense_id}", {
          params: { path: { expense_id: expense.id } },
          body,
          headers: { "If-Match": ifMatch(expense.version) },
        }),
      );
    },
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      queryClient.setQueryData(["expense", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["expenses"] });
      void navigate("/expenses");
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "stale_version") {
        setMessage("Someone else changed this expense. Reload the page to see their version.");
        return;
      }
      setMessage(applyServerErrors(e, setError, FIELDS));
    },
  });
  const voidIt = useMutation({
    mutationFn: async (x: Expense) =>
      unwrap(
        await api.POST("/api/v1/expenses/{expense_id}/void", {
          params: { path: { expense_id: x.id } },
          headers: { "If-Match": ifMatch(x.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["expenses"] });
      void queryClient.invalidateQueries({ queryKey: ["expense"] });
      void navigate("/expenses");
    },
    onError: (e) => {
      setMessage(e.message);
    },
  });

  return (
    <form
      noValidate
      className="grid max-w-3xl gap-6"
      onSubmit={(e) => {
        setMessage(null);
        void handleSubmit((v) => {
          save.mutate(v);
        })(e);
      }}
    >
      {message && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardContent>
          <fieldset disabled={voided} className="grid gap-4 sm:grid-cols-2">
            <Field id="category" label="Category" error={errors.category?.message}>
              <NativeSelect id="category" {...register("category")}>
                {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <TextField
              id="expense_date"
              label="Date"
              type="date"
              error={errors.expense_date?.message}
              registration={register("expense_date")}
            />
            <div className="sm:col-span-2">
              <TextField
                id="description"
                label="Description"
                error={errors.description?.message}
                registration={register("description")}
              />
            </div>
            <Field id="vendor" label="Vendor" error={errors.vendor_party_id?.message}>
              <Controller
                control={control}
                name="vendor_party_id"
                render={({ field }) => (
                  <PartyPicker
                    id="vendor"
                    role="vendor"
                    value={vendor}
                    onChange={(picked) => {
                      setVendor(picked);
                      field.onChange(picked?.id ?? "");
                    }}
                  />
                )}
              />
            </Field>
            <TextField
              id="vendor_bill_number"
              label="Vendor bill number"
              error={errors.vendor_bill_number?.message}
              registration={register("vendor_bill_number")}
            />
            <Field id="project_id" label="Project" error={errors.project_id?.message}>
              <NativeSelect id="project_id" {...register("project_id")}>
                <option value="">Office (no project)</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <div />
            <TextField
              id="taxable_value"
              label="Amount before GST (₹)"
              inputMode="decimal"
              error={errors.taxable_value?.message}
              registration={register("taxable_value")}
            />
            <TextField
              id="gst_amount"
              label="GST (₹)"
              inputMode="decimal"
              error={errors.gst_amount?.message}
              registration={register("gst_amount")}
            />
            <Field
              id="itc_eligible"
              label="Input tax credit"
              error={errors.itc_eligible?.message}
              hint="Claimable GST is not a cost of the project."
            >
              <label className="flex h-9 items-center gap-2 text-sm">
                <input id="itc_eligible" type="checkbox" {...register("itc_eligible")} />
                The GST can be claimed back
              </label>
            </Field>
            <div className="grid content-end pb-2 text-sm">
              Total{" "}
              <strong className="tabular-nums">{total === null ? "–" : formatInr(total)}</strong>
            </div>
            <TextField
              id="amount_paid"
              label="Paid so far (₹)"
              inputMode="decimal"
              error={errors.amount_paid?.message}
              registration={register("amount_paid")}
            />
            <Field id="payment_mode" label="Paid by" error={errors.payment_mode?.message}>
              <NativeSelect id="payment_mode" disabled={!paid.trim()} {...register("payment_mode")}>
                <option value="">–</option>
                {Object.entries(MODE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </fieldset>
        </CardContent>
      </Card>
      {!voided && (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending}>
            {expense ? "Save changes" : "Record expense"}
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to="/expenses">Cancel</Link>
          </Button>
          {expense && (
            <Button
              type="button"
              variant="ghost"
              className="ml-auto"
              disabled={voidIt.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "Void this expense? It is kept, marked voided, and stops counting.",
                  )
                ) {
                  voidIt.mutate(expense);
                }
              }}
            >
              Void expense
            </Button>
          )}
        </div>
      )}
    </form>
  );
}

export function ExpenseFormPage() {
  const { expenseId } = useParams();
  const expense = useQuery({
    queryKey: ["expense", expenseId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/expenses/{expense_id}", {
          params: { path: { expense_id: expenseId ?? "" } },
        }),
      ),
    enabled: expenseId !== undefined,
  });
  const header = (
    <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
      <Link to="/expenses">
        <ArrowLeft aria-hidden /> Expenses
      </Link>
    </Button>
  );
  if (expenseId === undefined) {
    return (
      <>
        {header}
        <PageHeader title="Record expense" />
        <ExpenseForm />
      </>
    );
  }
  if (expense.error) return <ErrorState error={expense.error} />;
  if (!expense.data) return <Skeleton className="h-96 w-full" />;
  return (
    <>
      {header}
      <PageHeader
        title={expense.data.description}
        description={
          expense.data.status === "VOIDED" ? <Badge variant="secondary">Voided</Badge> : undefined
        }
      />
      <ExpenseForm expense={expense.data} />
    </>
  );
}
