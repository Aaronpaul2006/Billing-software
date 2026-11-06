import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { Money } from "@/components/Money";
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
import { ifMatch } from "@/lib/forms";
import {
  cleanMoneyInput,
  formatQty,
  MONEY_INPUT,
  qtyTimesRate,
  sumMoney,
  toMilli,
} from "@/lib/money";

import { useWorkOrder, workOrderKey } from "./api";
import type { WorkOrderDetail } from "./api";

const PERCENT = /^\d{1,2}(\.\d{1,2})?$/;

interface Line {
  key: string;
  id?: string;
  boq_item_id: string | null;
  item_code: string;
  description: string;
  unit: string;
  qty: string;
  rate: string;
  gst_rate: string;
  billed: string; // already billed (edit): the quantity cannot go below it
}

let counter = 0;
function blank(over: Partial<Line> = {}): Line {
  counter += 1;
  return {
    key: `new-${String(counter)}`,
    boq_item_id: null,
    item_code: "",
    description: "",
    unit: "",
    qty: "",
    rate: "",
    gst_rate: "18",
    billed: "0",
    ...over,
  };
}

function problems(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || !e.problem.errors) return {};
  return Object.fromEntries(e.problem.errors.map((x) => [x.field ?? "", x.message]));
}

function fromOrder(wo: WorkOrderDetail): Line[] {
  return wo.items.map((i) => ({
    key: i.id,
    id: i.id,
    boq_item_id: i.boq_item_id ?? null,
    item_code: i.item_code,
    description: i.description,
    unit: i.unit,
    qty: formatQty(i.qty),
    rate: i.rate,
    gst_rate: String(Number(i.gst_rate)),
    billed: i.billed_qty,
  }));
}

function Form({ order }: { order?: WorkOrderDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const [projectId, setProjectId] = useState(order?.project_id ?? "");
  const [vendor, setVendor] = useState<PickedParty | null>(
    order ? { id: order.vendor_party_id, name: order.vendor_name } : null,
  );
  const [number, setNumber] = useState(order?.wo_number ?? "");
  const [date, setDate] = useState(order?.wo_date ?? isoDate(new Date()));
  const [title, setTitle] = useState(order?.title ?? "");
  const [terms, setTerms] = useState(order?.terms ?? "");
  const [retention, setRetention] = useState(order ? String(Number(order.retention_pct)) : "5");
  const [section, setSection] = useState(order ? (order.tds_section ?? "") : "194C");
  const [tdsRate, setTdsRate] = useState(order ? String(Number(order.tds_rate)) : "1");
  const [lines, setLines] = useState<Line[]>(order ? fromOrder(order) : [blank()]);
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
  const boq = useQuery({
    queryKey: ["boq-items", projectId],
    enabled: projectId !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/boq-items", {
          params: { path: { project_id: projectId }, query: { limit: 500 } },
        }),
      ).results,
  });

  const set = (key: string, change: Partial<Line>) => {
    setLines((now) => now.map((l) => (l.key === key ? { ...l, ...change } : l)));
  };
  const amounts = lines.map((l) => qtyTimesRate(l.qty, cleanMoneyInput(l.rate)) ?? "0.00");
  const total = sumMoney(amounts);

  const save = useMutation({
    mutationFn: async () => {
      const items = lines.map((l) => ({
        ...(l.id ? { id: l.id } : {}),
        boq_item_id: l.boq_item_id,
        item_code: l.item_code.trim(),
        description: l.description.trim(),
        unit: l.unit.trim(),
        qty: l.qty.trim(),
        rate: cleanMoneyInput(l.rate),
        gst_rate: l.gst_rate || "0",
      }));
      const common = {
        wo_number: number.trim(),
        wo_date: date,
        title: title.trim(),
        terms: terms.trim() || null,
        retention_pct: retention || "0",
        tds_section: section.trim().toUpperCase() || null,
        tds_rate: section.trim() ? tdsRate || "0" : null,
        items,
      };
      if (!order) {
        return unwrap(
          await api.POST("/api/v1/work-orders", {
            body: { ...common, project_id: projectId, vendor_party_id: vendor?.id ?? "" },
            headers: { "Idempotency-Key": key },
          }),
        );
      }
      return unwrap(
        await api.PATCH("/api/v1/work-orders/{wo_id}", {
          params: { path: { wo_id: order.id } },
          body: common,
          headers: { "If-Match": ifMatch(order.version) },
        }),
      );
    },
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      queryClient.setQueryData(workOrderKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["work-orders"] });
      void navigate(`/work-orders/${saved.id}`);
    },
    onError: (e) => {
      setErrors(problems(e));
      setMessage(
        e instanceof ApiError && e.code === "stale_version"
          ? "Someone else changed this work order. Reload the page to see their version."
          : e instanceof ApiError && e.problem.errors?.length
            ? (e.problem.errors.find((x) => x.field === "items")?.message ??
              "Check the boxes marked below.")
            : e.message,
      );
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    if (!order && !projectId) local.project_id = "Choose the project.";
    if (!order && !vendor) local.vendor_party_id = "Choose the subcontractor.";
    if (!title.trim()) local.title = "Say what work is let, in a line.";
    if (!PERCENT.test(retention || "0")) local.retention_pct = "A percentage, e.g. 5.";
    if (section.trim() && !PERCENT.test(tdsRate)) local.tds_rate = "Enter the TDS rate, e.g. 1.";
    lines.forEach((l, i) => {
      const at = `items[${String(i)}]`;
      if (!l.item_code.trim()) local[`${at}.item_code`] = "Code";
      if (!l.description.trim()) local[`${at}.description`] = "What work";
      if (!l.unit.trim()) local[`${at}.unit`] = "Unit";
      const q = toMilli(l.qty);
      if (q === null || q <= 0n) local[`${at}.qty`] = "Quantity";
      if (!MONEY_INPUT.test(cleanMoneyInput(l.rate))) local[`${at}.rate`] = "Rate";
    });
    if (lines.length === 0) local.items = "Add at least one item.";
    setErrors(local);
    setMessage(Object.keys(local).length ? "Check the boxes marked below." : null);
    if (Object.keys(local).length === 0) save.mutate();
  };

  const boqLeft = (boq.data ?? []).filter((b) => !lines.some((l) => l.boq_item_id === b.id));

  return (
    <form
      noValidate
      aria-label={order ? "Edit work order" : "New work order"}
      className="grid max-w-4xl gap-6"
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
          {order ? (
            <p className="text-sm sm:col-span-2">
              {order.project_code} · {order.project_name} — {order.vendor_name}
            </p>
          ) : (
            <>
              <Field id="project" label="Project" error={errors.project_id}>
                <NativeSelect
                  key={projects.data?.map((p) => p.id).join() ?? "loading"}
                  id="project"
                  value={projectId}
                  aria-invalid={!!errors.project_id}
                  onChange={(e) => {
                    setProjectId(e.target.value);
                  }}
                >
                  <option value="">Choose…</option>
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} · {p.name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field id="vendor" label="Subcontractor" error={errors.vendor_party_id}>
                <PartyPicker
                  id="vendor"
                  role="vendor"
                  value={vendor}
                  invalid={!!errors.vendor_party_id}
                  onChange={setVendor}
                />
              </Field>
            </>
          )}
          <div className="sm:col-span-2">
            <Field id="title" label="Work let" error={errors.title}>
              <Input
                id="title"
                placeholder="e.g. Brickwork and plastering, ground floor"
                value={title}
                aria-invalid={!!errors.title}
                onChange={(e) => {
                  setTitle(e.target.value);
                }}
              />
            </Field>
          </div>
          <Field
            id="number"
            label="Work order number"
            error={errors.wo_number}
            hint={order ? undefined : "Leave empty for the next number"}
          >
            <Input
              id="number"
              value={number}
              aria-invalid={!!errors.wo_number}
              onChange={(e) => {
                setNumber(e.target.value);
              }}
            />
          </Field>
          <Field id="date" label="Date" error={errors.wo_date}>
            <Input
              id="date"
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
              }}
            />
          </Field>
          <Field id="retention" label="Retention held (%)" error={errors.retention_pct}>
            <Input
              id="retention"
              inputMode="decimal"
              value={retention}
              aria-invalid={!!errors.retention_pct}
              onChange={(e) => {
                setRetention(e.target.value);
              }}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field id="tds-section" label="TDS section" error={errors.tds_section}>
              <Input
                id="tds-section"
                placeholder="none"
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
                value={tdsRate}
                disabled={!section.trim()}
                aria-invalid={!!errors.tds_rate}
                onChange={(e) => {
                  setTdsRate(e.target.value);
                }}
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field id="terms" label="Terms (optional)">
              <Input
                id="terms"
                placeholder="e.g. Materials by us; payment within 15 days of a certified bill"
                value={terms}
                onChange={(e) => {
                  setTerms(e.target.value);
                }}
              />
            </Field>
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="items-heading" className="grid gap-3">
        <h2 id="items-heading" className="text-section">
          Items
        </h2>
        {errors.items && <p className="text-destructive text-sm">{errors.items}</p>}
        <ol className="grid gap-3">
          {lines.map((l, i) => {
            const at = `items[${String(i)}]`;
            const err = (f: string) => errors[`${at}.${f}`];
            const billed = (toMilli(l.billed) ?? 0n) > 0n;
            return (
              <li
                key={l.key}
                aria-label={`Item ${String(i + 1)}`}
                className="border-border grid gap-3 rounded-md border p-3 sm:grid-cols-12"
              >
                <Field
                  id={`${l.key}-code`}
                  label="Code"
                  error={err("item_code")}
                  className="sm:col-span-2"
                >
                  <Input
                    id={`${l.key}-code`}
                    value={l.item_code}
                    aria-invalid={!!err("item_code")}
                    onChange={(e) => {
                      set(l.key, { item_code: e.target.value });
                    }}
                  />
                </Field>
                <Field
                  id={`${l.key}-desc`}
                  label="Work"
                  error={err("description")}
                  className="sm:col-span-10"
                >
                  <Input
                    id={`${l.key}-desc`}
                    value={l.description}
                    aria-invalid={!!err("description")}
                    onChange={(e) => {
                      set(l.key, { description: e.target.value });
                    }}
                  />
                </Field>
                <Field
                  id={`${l.key}-qty`}
                  label="Quantity"
                  error={err("qty")}
                  hint={billed ? `${formatQty(l.billed)} billed` : undefined}
                  className="sm:col-span-3"
                >
                  <Input
                    id={`${l.key}-qty`}
                    inputMode="decimal"
                    value={l.qty}
                    aria-invalid={!!err("qty")}
                    onChange={(e) => {
                      set(l.key, { qty: e.target.value });
                    }}
                  />
                </Field>
                <Field
                  id={`${l.key}-unit`}
                  label="Unit"
                  error={err("unit")}
                  className="sm:col-span-2"
                >
                  <Input
                    id={`${l.key}-unit`}
                    value={l.unit}
                    aria-invalid={!!err("unit")}
                    onChange={(e) => {
                      set(l.key, { unit: e.target.value });
                    }}
                  />
                </Field>
                <Field
                  id={`${l.key}-rate`}
                  label="Rate (₹)"
                  error={err("rate")}
                  className="sm:col-span-3"
                >
                  <Input
                    id={`${l.key}-rate`}
                    inputMode="decimal"
                    value={l.rate}
                    aria-invalid={!!err("rate")}
                    onChange={(e) => {
                      set(l.key, { rate: e.target.value });
                    }}
                  />
                </Field>
                <Field id={`${l.key}-gst`} label="GST %" className="sm:col-span-2">
                  <NativeSelect
                    id={`${l.key}-gst`}
                    value={l.gst_rate}
                    onChange={(e) => {
                      set(l.key, { gst_rate: e.target.value });
                    }}
                  >
                    {["0", "5", "12", "18", "28"].map((r) => (
                      <option key={r} value={r}>
                        {r} %
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <div className="flex items-end justify-between gap-2 sm:col-span-2 sm:flex-col sm:items-end">
                  <Money value={amounts[i] ?? "0.00"} className="text-sm" />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={billed}
                    title={billed ? "Billed: it stays" : undefined}
                    aria-label={`Remove item ${String(i + 1)}`}
                    onClick={() => {
                      setLines((now) => now.filter((x) => x.key !== l.key));
                    }}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </div>
              </li>
            );
          })}
        </ol>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setLines((now) => [...now, blank()]);
            }}
          >
            <Plus aria-hidden /> Add item
          </Button>
          {boqLeft.length > 0 && (
            <NativeSelect
              aria-label="Add from the client's BOQ"
              className="w-auto max-w-full"
              value=""
              onChange={(e) => {
                const b = boqLeft.find((x) => x.id === e.target.value);
                if (!b) return;
                setLines((now) => [
                  ...now.filter((x) => x.item_code || x.description || x.qty),
                  blank({
                    boq_item_id: b.id,
                    item_code: b.item_code,
                    description: b.description,
                    unit: b.unit,
                    qty: formatQty(b.contract_qty),
                    gst_rate: String(Number(b.gst_rate)),
                  }),
                ]);
              }}
            >
              <option value="">Add from the client's BOQ…</option>
              {boqLeft.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.item_code} · {b.description.slice(0, 60)}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
      </section>

      <SaveBar
        status={
          <>
            Work order value <Money value={total} strong />
          </>
        }
      >
        <Button type="button" variant="ghost" onClick={() => void navigate(-1)}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {order ? "Save changes" : "Save work order"}
        </Button>
      </SaveBar>
    </form>
  );
}

export function WorkOrderFormPage() {
  const { workOrderId } = useParams();
  const order = useWorkOrder(workOrderId);
  if (workOrderId && order.error) return <ErrorState error={order.error} />;
  if (workOrderId && !order.data) return <Skeleton className="h-96 w-full" />;
  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Work orders", to: "/work-orders" },
          ...(order.data
            ? [
                { label: order.data.wo_number, to: `/work-orders/${order.data.id}` },
                { label: "Edit" },
              ]
            : [{ label: "New" }]),
        ]}
      />
      <PageHeader
        title={order.data ? `Edit ${order.data.wo_number}` : "New work order"}
        description="The work let to a subcontractor, item by item at the agreed rates. RA bills are checked against it."
      />
      <Form key={order.data?.version ?? "new"} {...(order.data ? { order: order.data } : {})} />
    </>
  );
}
