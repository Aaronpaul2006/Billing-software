import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { Field, TextField } from "@/components/FormField";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { applyServerErrors, blankToNull, ifMatch } from "@/lib/forms";
import { STATE_OPTIONS, STATES } from "@/lib/india";
import { cleanMoneyInput } from "@/lib/money";

import { projectKey, STATUS_LABELS, useRegistrations } from "./api";
import type { Project, ProjectStatus } from "./api";

type ProjectWrite = components["schemas"]["ProjectWrite"];
type StateCode = ProjectWrite["site_state_code"];

const money = z
  .string()
  .refine(
    (v) => /^(\d{1,12}(\.\d{1,2})?)?$/.test(cleanMoneyInput(v)),
    "An amount like 4500000 or 4,50,000.50.",
  );
const percent = z
  .string()
  .trim()
  .regex(/^\d{1,3}(\.\d{1,2})?$/, "A percentage like 5 or 2.5.")
  .refine((v) => Number(v) <= 100, "At most 100.");

const formSchema = z
  .object({
    code: z
      .string()
      .trim()
      .regex(/^[A-Za-z0-9_-]{1,30}$/, "Letters, digits, - and _, up to 30."),
    name: z.string().trim().min(1, "Enter a name."),
    client_party_id: z.string().min(1, "Choose the client."),
    gst_registration_id: z.string().min(1, "Choose the registration you bill from."),
    site_state_code: z.string().min(1, "Choose the state of the site."),
    site_address: z.object({
      line1: z.string(),
      line2: z.string(),
      city: z.string(),
      pincode: z.string(),
    }),
    contract_value: money,
    retention_pct: percent,
    income_tax_tds_pct: percent,
    gst_tds_applicable: z.boolean(),
    mobilisation_advance: money,
    advance_recovery_pct: percent,
    status: z.enum(["PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"]),
    start_date: z.string(),
    end_date: z.string(),
  })
  .refine((v) => !v.start_date || !v.end_date || v.end_date >= v.start_date, {
    path: ["end_date"],
    message: "Ends before it starts.",
  });

type FormValues = z.infer<typeof formSchema>;

const FIELDS = [
  "code",
  "name",
  "client_party_id",
  "gst_registration_id",
  "site_state_code",
  "site_address.line1",
  "site_address.line2",
  "site_address.city",
  "site_address.pincode",
  "contract_value",
  "retention_pct",
  "income_tax_tds_pct",
  "gst_tds_applicable",
  "mobilisation_advance",
  "advance_recovery_pct",
  "status",
  "start_date",
  "end_date",
] as const;

function toForm(p: Project | undefined): FormValues {
  const a = p?.site_address;
  return {
    code: p?.code ?? "",
    name: p?.name ?? "",
    client_party_id: p?.client_party_id ?? "",
    gst_registration_id: p?.gst_registration_id ?? "",
    site_state_code: p?.site_state_code ?? "",
    site_address: {
      line1: a?.line1 ?? "",
      line2: a?.line2 ?? "",
      city: a?.city ?? "",
      pincode: a?.pincode ?? "",
    },
    contract_value: p?.contract_value ?? "",
    retention_pct: p?.retention_pct ?? "0",
    income_tax_tds_pct: p?.income_tax_tds_pct ?? "0",
    gst_tds_applicable: p?.gst_tds_applicable ?? false,
    mobilisation_advance: p?.mobilisation_advance ?? "0",
    advance_recovery_pct: p?.advance_recovery_pct ?? "0",
    status: p?.status ?? "ACTIVE",
    start_date: p?.start_date ?? "",
    end_date: p?.end_date ?? "",
  };
}

function toApi(v: FormValues): ProjectWrite {
  const a = v.site_address;
  const hasAddress = [a.line1, a.city, a.pincode].some((s) => s.trim() !== "");
  const state = v.site_state_code as StateCode;
  return {
    code: v.code.trim(),
    name: v.name.trim(),
    client_party_id: v.client_party_id,
    gst_registration_id: v.gst_registration_id,
    site_state_code: state,
    // The site address is in the site state by definition.
    site_address: hasAddress
      ? {
          line1: a.line1.trim(),
          ...(a.line2.trim() ? { line2: a.line2.trim() } : {}),
          city: a.city.trim(),
          state_code: state,
          pincode: a.pincode.trim(),
        }
      : null,
    contract_value: blankToNull(cleanMoneyInput(v.contract_value)),
    retention_pct: v.retention_pct.trim(),
    income_tax_tds_pct: v.income_tax_tds_pct.trim(),
    gst_tds_applicable: v.gst_tds_applicable,
    mobilisation_advance: cleanMoneyInput(v.mobilisation_advance) || "0",
    advance_recovery_pct: v.advance_recovery_pct.trim(),
    status: v.status,
    start_date: blankToNull(v.start_date),
    end_date: blankToNull(v.end_date),
  };
}

export function ProjectForm({ project }: { project?: Project }) {
  const isNew = project === undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const registrations = useRegistrations();
  const [client, setClient] = useState<PickedParty | null>(
    project ? { id: project.client_party_id, name: project.client_name } : null,
  );
  const [message, setMessage] = useState<{ kind: "error" | "saved"; text: string } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: toForm(project),
    values: project ? toForm(project) : undefined, // follow the saved project
  });
  const { register, handleSubmit, setError, formState, control } = form;
  const errors = formState.errors;

  const save = useMutation({
    mutationFn: async (values: FormValues) => {
      const body = toApi(values);
      if (!project) {
        return unwrap(
          await api.POST("/api/v1/projects", {
            body,
            headers: { "Idempotency-Key": idempotencyKey },
          }),
        );
      }
      return unwrap(
        await api.PATCH("/api/v1/projects/{project_id}", {
          params: { path: { project_id: project.id } },
          body,
          headers: { "If-Match": ifMatch(project.version) },
        }),
      );
    },
    onSuccess: (saved) => {
      setIdempotencyKey(newIdempotencyKey());
      queryClient.setQueryData(projectKey(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      setMessage({ kind: "saved", text: "Saved." });
      if (isNew) void navigate(`/projects/${saved.id}`, { replace: true });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "stale_version") {
        setMessage({
          kind: "error",
          text: "Someone else changed this project since you opened it. Reload to see their version.",
        });
        return;
      }
      const text = applyServerErrors(error, setError, FIELDS);
      setMessage(text ? { kind: "error", text } : null);
    },
  });

  return (
    <form
      noValidate
      className="grid max-w-3xl gap-6"
      onSubmit={(e) => {
        setMessage(null);
        void handleSubmit((values) => {
          save.mutate(values);
        })(e);
      }}
    >
      {message && (
        <Alert variant={message.kind === "error" ? "destructive" : "default"}>
          {message.kind === "error" ? <AlertCircle aria-hidden /> : <CheckCircle2 aria-hidden />}
          <AlertDescription className="flex flex-wrap items-center gap-2">
            {message.text}
            {message.text.startsWith("Someone else") && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setMessage(null);
                  void queryClient.invalidateQueries({ queryKey: projectKey(project?.id ?? "") });
                }}
              >
                Reload
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Project</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="code"
            label="Code"
            hint="Short and unique, e.g. VILLA-1."
            className="font-mono"
            error={errors.code?.message}
            registration={register("code")}
          />
          <TextField
            id="name"
            label="Name"
            error={errors.name?.message}
            registration={register("name")}
          />
          <Field id="client" label="Client" error={errors.client_party_id?.message}>
            <Controller
              control={control}
              name="client_party_id"
              render={({ field }) => (
                <PartyPicker
                  id="client"
                  value={client}
                  invalid={!!errors.client_party_id}
                  onChange={(picked) => {
                    setClient(picked);
                    field.onChange(picked?.id ?? "");
                  }}
                />
              )}
            />
          </Field>
          <Field id="status" label="Status" error={errors.status?.message}>
            <NativeSelect id="status" {...register("status")}>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <option key={value} value={value as ProjectStatus}>
                  {label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <TextField
            id="start_date"
            label="Start date"
            type="date"
            error={errors.start_date?.message}
            registration={register("start_date")}
          />
          <TextField
            id="end_date"
            label="End date"
            type="date"
            error={errors.end_date?.message}
            registration={register("end_date")}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>GST and site</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field
            id="gst_registration_id"
            label="Bill from"
            error={errors.gst_registration_id?.message}
            hint="Your GST registration for this project."
          >
            {registrations.data?.length === 0 && (
              <p className="text-destructive text-sm">
                No GST registration yet.{" "}
                <Link to="/settings/gst-registrations" className="underline">
                  Add one in Settings
                </Link>{" "}
                first.
              </p>
            )}
            {/* redrawn when the options arrive, so it shows the saved value (D.1) */}
            <NativeSelect
              key={registrations.data?.map((r) => r.id).join() ?? "loading"}
              id="gst_registration_id"
              {...register("gst_registration_id")}
            >
              <option value="">–</option>
              {registrations.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.gstin ?? "Unregistered"} · {r.state_name}
                  {r.is_default ? " (default)" : ""}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field
            id="site_state_code"
            label="Site state"
            error={errors.site_state_code?.message}
            hint="Place of supply for works on the site."
          >
            <NativeSelect id="site_state_code" {...register("site_state_code")}>
              <option value="">–</option>
              {STATE_OPTIONS.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <TextField
            id="site-line1"
            label="Site address"
            error={errors.site_address?.line1?.message}
            registration={register("site_address.line1")}
          />
          <TextField
            id="site-line2"
            label="Address line 2"
            error={errors.site_address?.line2?.message}
            registration={register("site_address.line2")}
          />
          <TextField
            id="site-city"
            label="City"
            error={errors.site_address?.city?.message}
            registration={register("site_address.city")}
          />
          <TextField
            id="site-pincode"
            label="PIN code"
            inputMode="numeric"
            maxLength={6}
            error={errors.site_address?.pincode?.message}
            registration={register("site_address.pincode")}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Contract and deductions</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="contract_value"
            label="Contract value (₹)"
            inputMode="decimal"
            error={errors.contract_value?.message}
            registration={register("contract_value")}
          />
          <TextField
            id="retention_pct"
            label="Retention (%)"
            inputMode="decimal"
            error={errors.retention_pct?.message}
            registration={register("retention_pct")}
          />
          <TextField
            id="income_tax_tds_pct"
            label="Income-tax TDS (%)"
            hint="s.194C: 1 % individuals / HUF, 2 % others."
            inputMode="decimal"
            error={errors.income_tax_tds_pct?.message}
            registration={register("income_tax_tds_pct")}
          />
          <Field id="gst_tds_applicable" label="GST TDS" error={errors.gst_tds_applicable?.message}>
            <label className="flex h-9 items-center gap-2 text-sm">
              <input id="gst_tds_applicable" type="checkbox" {...register("gst_tds_applicable")} />
              Client deducts 2 % GST TDS (s.51)
            </label>
          </Field>
          <TextField
            id="mobilisation_advance"
            label="Mobilisation advance (₹)"
            inputMode="decimal"
            error={errors.mobilisation_advance?.message}
            registration={register("mobilisation_advance")}
          />
          <TextField
            id="advance_recovery_pct"
            label="Advance recovery (%)"
            hint="Recovered from each bill until the advance is repaid."
            inputMode="decimal"
            error={errors.advance_recovery_pct?.message}
            registration={register("advance_recovery_pct")}
          />
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {isNew ? "Create project" : "Save changes"}
        </Button>
        {project && (
          <span className="text-muted-foreground self-center text-xs">
            Site state {STATES[project.site_state_code]}; client, registration and site state lock
            once the project is billed.
          </span>
        )}
      </div>
    </form>
  );
}
