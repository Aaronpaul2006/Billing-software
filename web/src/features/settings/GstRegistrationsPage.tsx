import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Plus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field, TextField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { applyServerErrors, blankToNull } from "@/lib/forms";
import { GSTIN_PATTERN, STATE_OPTIONS, STATES } from "@/lib/india";

type Create = components["schemas"]["GstRegistrationCreate"];
type StateCode = NonNullable<Create["state_code"]>;

const TYPES = [
  { value: "REGULAR", label: "Regular (charges GST)" },
  { value: "COMPOSITION", label: "Composition (bill of supply)" },
  { value: "UNREGISTERED", label: "Not registered for GST" },
] as const;

const formSchema = z
  .object({
    registration_type: z.enum(["REGULAR", "COMPOSITION", "UNREGISTERED"]),
    gstin: z.string(),
    state_code: z.string(),
    legal_name: z.string().trim().min(1, "Enter the legal name."),
    trade_name: z.string(),
    address: z.object({
      line1: z.string().trim().min(1, "Enter the address."),
      line2: z.string(),
      city: z.string().trim().min(1, "Enter the city."),
      pincode: z
        .string()
        .trim()
        .regex(/^[1-9][0-9]{5}$/, "A PIN code has 6 digits."),
    }),
    is_default: z.boolean(),
  })
  .refine(
    (v) =>
      v.registration_type === "UNREGISTERED" || GSTIN_PATTERN.test(v.gstin.trim().toUpperCase()),
    {
      path: ["gstin"],
      message: "Enter the 15-character GSTIN.",
    },
  )
  .refine((v) => v.registration_type !== "UNREGISTERED" || v.state_code !== "", {
    path: ["state_code"],
    message: "Choose the state.",
  });
type FormValues = z.infer<typeof formSchema>;

const FIELDS = [
  "registration_type",
  "gstin",
  "state_code",
  "legal_name",
  "trade_name",
  "address.line1",
  "address.line2",
  "address.city",
  "address.pincode",
  "is_default",
] as const;

function AddRegistration({ first, onDone }: { first: boolean; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      registration_type: "REGULAR",
      gstin: "",
      state_code: "",
      legal_name: "",
      trade_name: "",
      address: { line1: "", line2: "", city: "", pincode: "" },
      is_default: first,
    },
  });
  const { register, handleSubmit, formState, control } = form;
  const errors = formState.errors;
  const kind = useWatch({ control, name: "registration_type" });

  const save = useMutation({
    mutationFn: async (v: FormValues) => {
      const gstin = kind === "UNREGISTERED" ? null : v.gstin.trim().toUpperCase();
      // The address is in the registration's state: the GSTIN's first two digits.
      const state = (gstin ? gstin.slice(0, 2) : v.state_code) as StateCode;
      const body: Create = {
        registration_type: v.registration_type,
        gstin,
        ...(gstin ? {} : { state_code: state }),
        legal_name: v.legal_name.trim(),
        trade_name: blankToNull(v.trade_name),
        address: {
          line1: v.address.line1.trim(),
          ...(v.address.line2.trim() ? { line2: v.address.line2.trim() } : {}),
          city: v.address.city.trim(),
          state_code: state,
          pincode: v.address.pincode.trim(),
        },
        is_default: v.is_default,
      };
      return unwrap(
        await api.POST("/api/v1/gst-registrations", { body, headers: { "Idempotency-Key": key } }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["gst-registrations"] });
      onDone();
    },
    onError: (e) => {
      setError(applyServerErrors(e, form.setError, FIELDS));
    },
  });

  return (
    <form
      noValidate
      aria-label="New GST registration"
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
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="reg-type" label="Type" error={errors.registration_type?.message}>
          <NativeSelect id="reg-type" {...register("registration_type")}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {kind === "UNREGISTERED" ? (
          <Field id="reg-state" label="State" error={errors.state_code?.message}>
            <NativeSelect id="reg-state" {...register("state_code")}>
              <option value="">–</option>
              {STATE_OPTIONS.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
        ) : (
          <TextField
            id="reg-gstin"
            label="GSTIN"
            hint="The state is taken from it."
            className="font-mono uppercase"
            maxLength={15}
            error={errors.gstin?.message}
            registration={register("gstin")}
          />
        )}
        <TextField
          id="reg-legal"
          label="Legal name"
          error={errors.legal_name?.message}
          registration={register("legal_name")}
        />
        <TextField
          id="reg-trade"
          label="Trade name"
          error={errors.trade_name?.message}
          registration={register("trade_name")}
        />
        <TextField
          id="reg-line1"
          label="Address"
          error={errors.address?.line1?.message}
          registration={register("address.line1")}
        />
        <TextField
          id="reg-line2"
          label="Address line 2"
          error={errors.address?.line2?.message}
          registration={register("address.line2")}
        />
        <TextField
          id="reg-city"
          label="City"
          error={errors.address?.city?.message}
          registration={register("address.city")}
        />
        <TextField
          id="reg-pincode"
          label="PIN code"
          inputMode="numeric"
          maxLength={6}
          error={errors.address?.pincode?.message}
          registration={register("address.pincode")}
        />
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" {...register("is_default")} /> Default for new documents
        </label>
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Add registration
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function GstRegistrationsPage() {
  const [adding, setAdding] = useState(false);
  const registrations = useQuery({
    queryKey: ["gst-registrations", "all"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/gst-registrations", { params: { query: { limit: 100 } } }))
        .results,
  });
  const rows = registrations.data ?? [];
  return (
    <>
      <PageHeader
        title="GST registrations"
        description="The GSTINs you bill from. Each project bills from one of them."
        actions={
          !adding && (
            <Button
              onClick={() => {
                setAdding(true);
              }}
            >
              <Plus aria-hidden /> Add registration
            </Button>
          )
        }
      />
      {adding && (
        <AddRegistration
          first={rows.length === 0}
          onDone={() => {
            setAdding(false);
          }}
        />
      )}
      {registrations.error ? (
        <ErrorState error={registrations.error} />
      ) : registrations.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No registration yet. Add your GSTIN (or register as unregistered) before creating
          projects.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>GSTIN</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>
                <span className="sr-only">Status</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono">{r.gstin ?? "–"}</TableCell>
                <TableCell>
                  {r.legal_name}
                  {r.trade_name && (
                    <div className="text-muted-foreground text-xs">{r.trade_name}</div>
                  )}
                </TableCell>
                <TableCell>{STATES[r.state_code] ?? r.state_code}</TableCell>
                <TableCell>{TYPES.find((t) => t.value === r.registration_type)?.label}</TableCell>
                <TableCell className="flex gap-1">
                  {r.is_default && <Badge>Default</Badge>}
                  {!r.is_active && <Badge variant="secondary">Inactive</Badge>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
