import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { Field, TextField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { NEEDS_GSTIN, TREATMENTS } from "@/features/parties/gst";
import type { Treatment } from "@/features/parties/gst";
import { applyServerErrors, blankToNull } from "@/lib/forms";
import { STATE_OPTIONS } from "@/lib/india";
import { cleanMoneyInput } from "@/lib/money";

type CatalogItem = components["schemas"]["CatalogItem"];
type Party = components["schemas"]["Party"];

const GST_RATES = ["0.00", "5.00", "12.00", "18.00", "28.00"];

interface ItemForm {
  name: string;
  unit: string;
  sac_hsn: string;
  default_rate: string;
  gst_rate: string;
}

/** "New item" while making a bill: saved to the catalog, then put on the line. */
export function NewItemDialog({
  name,
  onClose,
  onCreated,
}: {
  name: string;
  onClose: () => void;
  onCreated: (item: CatalogItem) => void;
}) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [message, setMessage] = useState<string | null>(null);
  const { register, handleSubmit, setError, formState } = useForm<ItemForm>({
    defaultValues: { name, unit: "", sac_hsn: "", default_rate: "", gst_rate: "18.00" },
  });
  const errors = formState.errors;
  const save = useMutation({
    mutationFn: async (v: ItemForm) =>
      unwrap(
        await api.POST("/api/v1/catalog-items", {
          body: {
            name: v.name.trim(),
            unit: blankToNull(v.unit.trim()),
            sac_hsn: blankToNull(v.sac_hsn.trim()),
            default_rate: blankToNull(cleanMoneyInput(v.default_rate)),
            gst_rate: v.gst_rate,
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (item) => {
      void queryClient.invalidateQueries({ queryKey: ["catalog-items"] });
      onCreated(item);
    },
    onError: (e) => {
      setMessage(
        applyServerErrors(e, setError, ["name", "unit", "sac_hsn", "default_rate", "gst_rate"]),
      );
    },
  });
  return (
    <Modal title="New item" onClose={onClose}>
      <form
        noValidate
        aria-label="New item"
        className="grid gap-3"
        onSubmit={(e) => {
          e.stopPropagation(); // not the bill's form
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
        <TextField
          id="new-item-name"
          label="Item name"
          error={errors.name?.message}
          registration={register("name", { validate: (v) => v.trim() !== "" || "Enter a name." })}
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField
            id="new-item-unit"
            label="Unit"
            placeholder="bag, cum, sqm…"
            error={errors.unit?.message}
            registration={register("unit")}
          />
          <TextField
            id="new-item-hsn"
            label="HSN / SAC code"
            inputMode="numeric"
            error={errors.sac_hsn?.message}
            registration={register("sac_hsn")}
          />
          <TextField
            id="new-item-rate"
            label="Rate (₹)"
            inputMode="decimal"
            error={errors.default_rate?.message}
            registration={register("default_rate")}
          />
          <Field id="new-item-gst" label="GST %" error={errors.gst_rate?.message}>
            <NativeSelect id="new-item-gst" {...register("gst_rate")}>
              {GST_RATES.map((r) => (
                <option key={r} value={r}>
                  {r.replace(".00", "")} %
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            Save item
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface ClientForm {
  display_name: string;
  gst_treatment: Treatment;
  gstin: string;
  state_code: string;
  email: string;
  phone: string;
}

/** "New client" while making a bill: saved to the clients, then chosen on the bill. */
export function NewClientDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (party: Party) => void;
}) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [message, setMessage] = useState<string | null>(null);
  const { register, handleSubmit, setError, formState, control } = useForm<ClientForm>({
    defaultValues: {
      display_name: "",
      gst_treatment: "UNREGISTERED",
      gstin: "",
      state_code: "",
      email: "",
      phone: "",
    },
  });
  const treatment = useWatch({ control, name: "gst_treatment" });
  const errors = formState.errors;
  const needsGstin = NEEDS_GSTIN.has(treatment);
  const save = useMutation({
    mutationFn: async (v: ClientForm) =>
      unwrap(
        await api.POST("/api/v1/parties", {
          body: {
            display_name: v.display_name.trim(),
            gst_treatment: v.gst_treatment,
            gstin: needsGstin ? blankToNull(v.gstin.trim().toUpperCase()) : null,
            // with a GSTIN, the server takes the state from it
            state_code: needsGstin
              ? null
              : ((blankToNull(v.state_code) as components["schemas"]["StateCodeEnum"] | null) ??
                null),
            email: blankToNull(v.email.trim()),
            phone: blankToNull(v.phone.trim()),
            is_customer: true,
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (party) => {
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      onCreated(party);
    },
    onError: (e) => {
      setMessage(
        applyServerErrors(e, setError, [
          "display_name",
          "gst_treatment",
          "gstin",
          "state_code",
          "email",
          "phone",
        ]),
      );
    },
  });
  return (
    <Modal title="New client" onClose={onClose}>
      <form
        noValidate
        aria-label="New client"
        className="grid gap-3"
        onSubmit={(e) => {
          e.stopPropagation(); // not the bill's form
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
        <TextField
          id="new-client-name"
          label="Client name"
          error={errors.display_name?.message}
          registration={register("display_name", {
            validate: (v) => v.trim() !== "" || "Enter a name.",
          })}
        />
        <Field id="new-client-gst" label="GST" error={errors.gst_treatment?.message}>
          <NativeSelect id="new-client-gst" {...register("gst_treatment")}>
            {TREATMENTS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {needsGstin ? (
          <TextField
            id="new-client-gstin"
            label="GSTIN"
            hint="15 characters; the state is read from it."
            autoCapitalize="characters"
            error={errors.gstin?.message}
            registration={register("gstin")}
          />
        ) : (
          <Field id="new-client-state" label="State" error={errors.state_code?.message}>
            <NativeSelect id="new-client-state" {...register("state_code")}>
              <option value="">Choose…</option>
              {STATE_OPTIONS.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <TextField
            id="new-client-email"
            label="Email"
            type="email"
            error={errors.email?.message}
            registration={register("email")}
          />
          <TextField
            id="new-client-phone"
            label="Phone"
            inputMode="tel"
            error={errors.phone?.message}
            registration={register("phone")}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            Save client
          </Button>
        </div>
      </form>
    </Modal>
  );
}
