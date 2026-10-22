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
import { applyServerErrors, blankToNull, ifMatch } from "@/lib/forms";
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

type Registration = components["schemas"]["GstRegistration"];

/** GSTIN, type and state are fixed (register again to change them); the rest may change. */
/** 2026 → "2026-27". */
function fyLabel(startYear: number): string {
  return `${String(startYear)}-${String((startYear + 1) % 100).padStart(2, "0")}`;
}

function EditRegistration({
  registration,
  onDone,
}: {
  registration: Registration;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const a = registration.address as Partial<Record<string, string>>;
  const [legalName, setLegalName] = useState(registration.legal_name);
  const [tradeName, setTradeName] = useState(registration.trade_name ?? "");
  const [line1, setLine1] = useState(a.line1 ?? "");
  const [line2, setLine2] = useState(a.line2 ?? "");
  const [city, setCity] = useState(a.city ?? "");
  const [pincode, setPincode] = useState(a.pincode ?? "");
  const [isDefault, setIsDefault] = useState(registration.is_default);
  const [isActive, setIsActive] = useState(registration.is_active);
  const [lutArn, setLutArn] = useState(registration.lut_arn ?? "");
  const [lutFy, setLutFy] = useState(
    registration.lut_fy_start_year === null ? "" : String(registration.lut_fy_start_year),
  );
  const [error, setError] = useState<string | null>(null);
  const regular = registration.registration_type === "REGULAR";
  const thisFy = fyStartYear(new Date());
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/gst-registrations/{registration_id}", {
          params: { path: { registration_id: registration.id } },
          body: {
            legal_name: legalName.trim(),
            trade_name: blankToNull(tradeName),
            address: {
              line1: line1.trim(),
              ...(line2.trim() ? { line2: line2.trim() } : {}),
              city: city.trim(),
              ...(a.district ? { district: a.district } : {}), // no field for it: kept as it is
              pincode: pincode.trim(),
              state_code: registration.state_code as StateCode,
            },
            is_default: isDefault,
            is_active: isActive,
            ...(regular
              ? {
                  lut_arn: blankToNull(lutArn.replace(/\s/g, "").toUpperCase()),
                  lut_fy_start_year: lutArn.trim() && lutFy ? Number(lutFy) : null,
                }
              : {}),
          },
          headers: { "If-Match": ifMatch(registration.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["gst-registrations"] });
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
  const text = (id: string, label: string, value: string, set: (v: string) => void) => (
    <Field id={id} label={label}>
      <Input
        id={id}
        value={value}
        onChange={(e) => {
          set(e.target.value);
        }}
      />
    </Field>
  );
  return (
    <form
      aria-label={`Edit ${registration.gstin ?? registration.legal_name}`}
      className="grid gap-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        save.mutate();
      }}
    >
      {text(`reg-${registration.id}-legal`, "Legal name", legalName, setLegalName)}
      {text(`reg-${registration.id}-trade`, "Trade name", tradeName, setTradeName)}
      {text(`reg-${registration.id}-line1`, "Address", line1, setLine1)}
      {text(`reg-${registration.id}-line2`, "Address line 2", line2, setLine2)}
      {text(`reg-${registration.id}-city`, "City", city, setCity)}
      {text(`reg-${registration.id}-pin`, "PIN code", pincode, setPincode)}
      <div className="grid content-end gap-1 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={(e) => {
              setIsDefault(e.target.checked);
            }}
          />
          Default
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => {
              setIsActive(e.target.checked);
            }}
          />
          Active
        </label>
      </div>
      {regular && (
        <>
          <Field
            id={`reg-${registration.id}-lut`}
            label="LUT ARN"
            hint="Letter of Undertaking (RFD-11): SEZ and export supplies without IGST."
          >
            <Input
              id={`reg-${registration.id}-lut`}
              className="font-mono uppercase"
              maxLength={20}
              value={lutArn}
              onChange={(e) => {
                setLutArn(e.target.value);
              }}
            />
          </Field>
          <Field id={`reg-${registration.id}-lut-fy`} label="LUT for financial year">
            <NativeSelect
              id={`reg-${registration.id}-lut-fy`}
              value={lutFy}
              onChange={(e) => {
                setLutFy(e.target.value);
              }}
            >
              <option value="">–</option>
              {[thisFy - 1, thisFy, thisFy + 1].map((y) => (
                <option key={y} value={String(y)}>
                  {fyLabel(y)}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </>
      )}
      {error && <p className="text-destructive text-sm sm:col-span-3">{error}</p>}
      <div className="flex gap-2 sm:col-span-3">
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

export function GstRegistrationsPage() {
  const [editing, setEditing] = useState<string | null>(null);
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
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) =>
              editing === r.id ? (
                <TableRow key={r.id}>
                  <TableCell colSpan={6}>
                    <EditRegistration
                      registration={r}
                      onDone={() => {
                        setEditing(null);
                      }}
                    />
                  </TableCell>
                </TableRow>
              ) : (
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
                    {r.lut_fy_start_year !== null && (
                      <Badge variant="outline">LUT {fyLabel(r.lut_fy_start_year)}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(r.id);
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
