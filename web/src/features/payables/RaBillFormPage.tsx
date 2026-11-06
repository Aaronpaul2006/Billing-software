import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SaveBar } from "@/components/SaveBar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { formatQty, qtyTimesRate, toMilli } from "@/lib/money";

import { useWorkOrder, vendorBillKey, workOrderKey } from "./api";
import { raTotals } from "./raTotals";
import type { WorkOrderDetail, WorkOrderItem } from "./api";

function problems(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !e.problem.errors) return {};
  return Object.fromEntries(e.problem.errors.map((x) => [x.field ?? "", x.message]));
}

/** "40" + "10.5" -> "50.5" (quantities to 3 decimals, exact). */
function addQty(a: string, b: string): string {
  const total = (toMilli(a) ?? 0n) + (toMilli(b) ?? 0n);
  return formatQty(`${String(total / 1000n)}.${String(total % 1000n).padStart(3, "0")}`);
}

function ItemRow({
  item,
  value,
  error,
  onChange,
}: {
  item: WorkOrderItem;
  value: string;
  error: string | undefined;
  onChange: (v: string) => void;
}) {
  const id = `qty-${item.id}`;
  const amount = qtyTimesRate(value, item.rate);
  const over =
    value.trim() !== "" &&
    (toMilli(value) === null || (toMilli(value) ?? 0n) > (toMilli(item.balance_qty) ?? 0n));
  return (
    <tr className="border-border border-b align-top max-sm:grid max-sm:grid-cols-2 max-sm:gap-x-3 max-sm:gap-y-2 max-sm:py-3">
      <td className="py-2 pr-3 max-sm:col-span-2 max-sm:py-0">
        <span className="font-medium">{item.item_code}</span> {item.description}
        <div className="text-help text-muted-foreground">
          Agreed {formatQty(item.qty)} {item.unit} at <Money value={item.rate} /> · left{" "}
          {formatQty(item.balance_qty)}
        </div>
      </td>
      <td className="py-2 pr-3 text-right whitespace-nowrap max-sm:py-0 max-sm:text-left">
        <span className="text-muted-foreground block text-xs sm:hidden">Up to last bill</span>
        {formatQty(item.billed_qty)} {item.unit}
      </td>
      <td className="py-2 pr-3 max-sm:py-0 sm:w-32">
        <span aria-hidden className="text-muted-foreground block text-xs sm:hidden">
          This bill
        </span>
        <label htmlFor={id} className="sr-only">
          This bill, item {item.item_code} ({item.unit})
        </label>
        <Input
          id={id}
          inputMode="decimal"
          className="text-right"
          value={value}
          aria-invalid={over || !!error}
          onChange={(e) => {
            onChange(e.target.value);
          }}
        />
        {(error ?? over) && (
          <p className="text-destructive mt-1 text-xs">
            {error ?? `At most ${formatQty(item.balance_qty)}`}
          </p>
        )}
      </td>
      <td className="py-2 pr-3 text-right whitespace-nowrap max-sm:py-0 max-sm:text-left">
        <span className="text-muted-foreground block text-xs sm:hidden">Up to date</span>
        {addQty(item.billed_qty, value)} {item.unit}
      </td>
      <td className="py-2 text-right whitespace-nowrap max-sm:py-0">
        <span className="text-muted-foreground block text-xs sm:hidden">Amount</span>
        <Money value={value.trim() && amount ? amount : "0.00"} muted={!value.trim()} />
      </td>
    </tr>
  );
}

function Form({ order }: { order: WorkOrderDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const [number, setNumber] = useState("");
  const [billDate, setBillDate] = useState(isoDate(new Date()));
  const [dueDate, setDueDate] = useState("");
  const [qty, setQty] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const t = raTotals(order, qty);
  const nextRa =
    Math.max(
      0,
      ...order.ra_bills.filter((b) => b.status === "RECORDED").map((b) => b.ra_number ?? 0),
    ) + 1;
  const lineItems = order.items.filter((i) => (toMilli(qty[i.id] ?? "") ?? 0n) > 0n);

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/work-orders/{wo_id}/ra-bills", {
          params: { path: { wo_id: order.id } },
          body: {
            bill_number: number.trim(),
            bill_date: billDate,
            due_date: dueDate || null,
            lines: lineItems.map((i) => ({
              work_order_item_id: i.id,
              qty: (qty[i.id] ?? "").trim(),
            })),
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      queryClient.setQueryData(vendorBillKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: workOrderKey(order.id) });
      void queryClient.invalidateQueries({ queryKey: ["work-orders"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      void navigate(`/vendor-bills/${saved.id}`);
    },
    onError: (e) => {
      const byField = problems(e);
      // lines[n].qty -> the item's own box
      const mapped: Record<string, string> = {};
      for (const [field, text] of Object.entries(byField)) {
        const m = /^lines\[(\d+)\]/.exec(field);
        const item = m ? lineItems[Number(m[1])] : undefined;
        mapped[item ? item.id : field] = text;
      }
      setErrors(mapped);
      setMessage(
        e instanceof ApiError && e.problem.errors?.length
          ? "Check the boxes marked below."
          : e.message,
      );
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    if (!number.trim()) local.bill_number = "Enter their bill number.";
    for (const i of order.items) {
      const v = (qty[i.id] ?? "").trim();
      if (!v) continue;
      const m = toMilli(v);
      if (m === null) local[i.id] = "A quantity, up to 3 decimals.";
      else if (m > (toMilli(i.balance_qty) ?? 0n))
        local[i.id] = `At most ${formatQty(i.balance_qty)}; amend the work order to bill more.`;
    }
    if (t.count === 0) local.lines = "Enter this bill's quantity of at least one item.";
    setErrors(local);
    setMessage(Object.keys(local).length ? "Check the boxes marked below." : null);
    if (Object.keys(local).length === 0) save.mutate();
  };

  return (
    <form
      noValidate
      aria-label="Record RA bill"
      className="grid max-w-5xl min-w-0 gap-6 [&>*]:min-w-0"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {message && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{errors.lines ?? message}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-3">
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
        </CardContent>
      </Card>

      <section aria-labelledby="abstract-heading">
        <h2 id="abstract-heading" className="text-section mb-2">
          Quantities: RA bill {nextRa}
        </h2>
        <div>
          <table className="w-full text-sm max-sm:block">
            <thead className="max-sm:hidden">
              <tr className="text-muted-foreground border-border border-b text-left text-xs">
                <th className="py-2 pr-3 font-medium">Item</th>
                <th className="py-2 pr-3 text-right font-medium">Up to last bill</th>
                <th className="py-2 pr-3 text-right font-medium">This bill</th>
                <th className="py-2 pr-3 text-right font-medium">Up to date</th>
                <th className="py-2 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody className="max-sm:block">
              {order.items.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  value={qty[item.id] ?? ""}
                  error={errors[item.id]}
                  onChange={(v) => {
                    setQty((now) => ({ ...now, [item.id]: v }));
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Card className="max-w-md justify-self-end">
        <CardContent>
          <dl className="grid gap-1 text-sm" aria-label="What we pay">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Value of work</dt>
              <dd>
                <Money value={t.taxable} />
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">GST</dt>
              <dd>
                <Money value={t.gst} />
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">
                {order.tds_section
                  ? `Less TDS ${order.tds_section} at ${String(Number(order.tds_rate))} %`
                  : "TDS"}
              </dt>
              <dd className="whitespace-nowrap">
                − <Money value={t.tds} />
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">
                Less retention at {String(Number(order.retention_pct))} %
              </dt>
              <dd className="whitespace-nowrap">
                − <Money value={t.retention} />
              </dd>
            </div>
            <div className="border-border mt-1 flex justify-between gap-4 border-t pt-1 font-semibold">
              <dt>We pay</dt>
              <dd>
                <Money value={t.net} strong />
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <SaveBar status={`${String(t.count)} ${t.count === 1 ? "item" : "items"} on this bill`}>
        <Button type="button" variant="ghost" onClick={() => void navigate(-1)}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          Save RA bill
        </Button>
      </SaveBar>
    </form>
  );
}

export function RaBillFormPage() {
  const { workOrderId = "" } = useParams();
  const order = useWorkOrder(workOrderId);
  if (order.error) return <ErrorState error={order.error} />;
  if (!order.data) return <Skeleton className="h-96 w-full" />;
  const wo = order.data;
  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Work orders", to: "/work-orders" },
          { label: wo.wo_number, to: `/work-orders/${wo.id}` },
          { label: "RA bill" },
        ]}
      />
      <PageHeader
        title={`RA bill from ${wo.vendor_name}`}
        description={`${wo.wo_number} · ${wo.title}. Enter this bill's quantity of each item; we work out the rest.`}
      />
      {wo.status === "OPEN" ? (
        <Form order={wo} />
      ) : (
        <Alert>
          <AlertDescription>This work order is closed; reopen it to enter a bill.</AlertDescription>
        </Alert>
      )}
    </>
  );
}
