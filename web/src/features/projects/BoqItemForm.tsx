import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { TextField } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { applyServerErrors, blankToNull, ifMatch } from "@/lib/forms";
import { cleanMoneyInput } from "@/lib/money";

import type { BoqItem } from "./api";

const formSchema = z.object({
  item_code: z.string().trim().min(1, "Enter the item code.").max(30),
  description: z.string().trim().min(1, "Describe the item.").max(2000),
  unit: z.string().trim().min(1, "e.g. cum, sqm, nos.").max(20),
  sac_hsn: z
    .string()
    .trim()
    .regex(/^([0-9]{4,8})?$/, "4 to 8 digits."),
  contract_qty: z
    .string()
    .trim()
    .regex(/^\d{1,11}(\.\d{1,3})?$/, "A quantity like 42.5 (up to 3 decimals)."),
  rate: z
    .string()
    .refine(
      (v) => /^\d{1,12}(\.\d{1,2})?$/.test(cleanMoneyInput(v)),
      "A rate like 6800 or 6800.50.",
    ),
  gst_rate: z
    .string()
    .trim()
    .regex(/^\d{1,2}(\.\d{1,2})?$/, "A rate like 18 or 12.5."),
  is_variation: z.boolean(),
});
type FormValues = z.infer<typeof formSchema>;

const FIELDS = [
  "item_code",
  "description",
  "unit",
  "sac_hsn",
  "contract_qty",
  "rate",
  "gst_rate",
  "is_variation",
] as const;

/** Add a BOQ item to a project, or edit one (If-Match). */
export function BoqItemForm({
  projectId,
  item,
  onDone,
}: {
  projectId: string;
  item?: BoqItem;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [idempotencyKey] = useState(newIdempotencyKey);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      item_code: item?.item_code ?? "",
      description: item?.description ?? "",
      unit: item?.unit ?? "",
      sac_hsn: item?.sac_hsn ?? "",
      contract_qty: item?.contract_qty ?? "",
      rate: item?.rate ?? "",
      gst_rate: item?.gst_rate ?? "18",
      is_variation: item?.is_variation ?? false,
    },
  });
  const { register, handleSubmit, formState } = form;
  const errors = formState.errors;

  const save = useMutation({
    mutationFn: async (v: FormValues) => {
      const body = {
        item_code: v.item_code.trim(),
        description: v.description.trim(),
        unit: v.unit.trim(),
        sac_hsn: blankToNull(v.sac_hsn),
        contract_qty: v.contract_qty.trim(),
        rate: cleanMoneyInput(v.rate),
        gst_rate: v.gst_rate.trim(),
        is_variation: v.is_variation,
      };
      if (item) {
        return unwrap(
          await api.PATCH("/api/v1/boq-items/{item_id}", {
            params: { path: { item_id: item.id } },
            body,
            headers: { "If-Match": ifMatch(item.version) },
          }),
        );
      }
      return unwrap(
        await api.POST("/api/v1/projects/{project_id}/boq-items", {
          params: { path: { project_id: projectId } },
          body,
          headers: { "Idempotency-Key": idempotencyKey },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["boq", projectId] });
      onDone();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "stale_version") {
        setError("Someone else changed this item. Close and open it again.");
        return;
      }
      setError(applyServerErrors(e, form.setError, FIELDS));
    },
  });

  return (
    <form
      noValidate
      aria-label={item ? `Edit item ${item.item_code}` : "New BOQ item"}
      className="bg-muted/40 grid gap-4 rounded-lg border p-4"
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
      <div className="grid gap-4 sm:grid-cols-4">
        <TextField
          id="boq-code"
          label="Item code"
          error={errors.item_code?.message}
          registration={register("item_code")}
        />
        <div className="sm:col-span-3">
          <TextField
            id="boq-description"
            label="Description"
            error={errors.description?.message}
            registration={register("description")}
          />
        </div>
        <TextField
          id="boq-unit"
          label="Unit"
          error={errors.unit?.message}
          registration={register("unit")}
        />
        <TextField
          id="boq-qty"
          label="Contract quantity"
          inputMode="decimal"
          error={errors.contract_qty?.message}
          registration={register("contract_qty")}
        />
        <TextField
          id="boq-rate"
          label="Rate (₹)"
          inputMode="decimal"
          error={errors.rate?.message}
          registration={register("rate")}
        />
        <TextField
          id="boq-gst"
          label="GST %"
          inputMode="decimal"
          error={errors.gst_rate?.message}
          registration={register("gst_rate")}
        />
        <TextField
          id="boq-sac"
          label="SAC / HSN"
          inputMode="numeric"
          error={errors.sac_hsn?.message}
          registration={register("sac_hsn")}
        />
        <label className="flex items-end gap-2 pb-2 text-sm sm:col-span-3">
          <input type="checkbox" {...register("is_variation")} />
          Variation (extra item): may be billed beyond the contract quantity
        </label>
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {item ? "Save item" : "Add item"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
