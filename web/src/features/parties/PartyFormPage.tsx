import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import type { UseFormRegisterReturn } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { z } from "zod";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { applyServerErrors, blankToNull, ifMatch } from "@/lib/forms";
import { STATE_OPTIONS } from "@/lib/india";

type Party = components["schemas"]["Party"];
type PartyWrite = components["schemas"]["PartyWrite"];
type Treatment = PartyWrite["gst_treatment"];

const TREATMENTS: { value: Treatment; label: string }[] = [
  { value: "REGISTERED", label: "Registered business (has GSTIN)" },
  { value: "COMPOSITION", label: "Composition dealer (has GSTIN)" },
  { value: "SEZ", label: "SEZ unit (has GSTIN)" },
  { value: "UNREGISTERED", label: "Unregistered business" },
  { value: "CONSUMER", label: "Consumer (individual)" },
  { value: "OVERSEAS", label: "Overseas" },
];
const NEEDS_GSTIN: ReadonlySet<Treatment> = new Set(["REGISTERED", "COMPOSITION", "SEZ"]);

const formSchema = z
  .object({
    display_name: z.string().trim().min(1, "Enter a name."),
    legal_name: z.string(),
    gst_treatment: z.enum([
      "REGISTERED",
      "COMPOSITION",
      "SEZ",
      "UNREGISTERED",
      "CONSUMER",
      "OVERSEAS",
    ]),
    gstin: z.string(),
    pan: z.string(),
    state_code: z.string(),
    is_customer: z.boolean(),
    is_vendor: z.boolean(),
    email: z.string(),
    phone: z.string(),
    billing_address: z.object({
      line1: z.string(),
      line2: z.string(),
      city: z.string(),
      state_code: z.string(),
      pincode: z.string(),
      country: z.string(),
    }),
  })
  .refine((v) => v.is_customer || v.is_vendor, {
    path: ["is_customer"],
    message: "A party is a customer, a vendor, or both.",
  })
  .refine((v) => !NEEDS_GSTIN.has(v.gst_treatment) || v.gstin.trim() !== "", {
    path: ["gstin"],
    message: "This party needs its GSTIN.",
  });

type FormValues = z.infer<typeof formSchema>;

const FIELDS = [
  "display_name",
  "legal_name",
  "gst_treatment",
  "gstin",
  "pan",
  "state_code",
  "is_customer",
  "is_vendor",
  "email",
  "phone",
  "billing_address.line1",
  "billing_address.line2",
  "billing_address.city",
  "billing_address.state_code",
  "billing_address.pincode",
  "billing_address.country",
] as const;

const EMPTY: FormValues = {
  display_name: "",
  legal_name: "",
  gst_treatment: "REGISTERED",
  gstin: "",
  pan: "",
  state_code: "",
  is_customer: true,
  is_vendor: false,
  email: "",
  phone: "",
  billing_address: { line1: "", line2: "", city: "", state_code: "", pincode: "", country: "IN" },
};

function toForm(p: Party): FormValues {
  const a = (p.billing_address ?? {}) as Partial<Record<string, string>>;
  return {
    display_name: p.display_name,
    legal_name: p.legal_name ?? "",
    gst_treatment: p.gst_treatment,
    gstin: p.gstin ?? "",
    pan: p.pan ?? "",
    state_code: p.state_code ?? "",
    is_customer: p.is_customer,
    is_vendor: p.is_vendor,
    email: p.email ?? "",
    phone: p.phone ?? "",
    billing_address: {
      line1: a.line1 ?? "",
      line2: a.line2 ?? "",
      city: a.city ?? "",
      state_code: a.state_code ?? "",
      pincode: a.pincode ?? "",
      country: a.country ?? "IN",
    },
  };
}

function toApi(v: FormValues): PartyWrite {
  const gstin = NEEDS_GSTIN.has(v.gst_treatment) ? blankToNull(v.gstin.toUpperCase()) : null;
  const a = v.billing_address;
  const overseas = v.gst_treatment === "OVERSEAS";
  const hasAddress = [a.line1, a.city].some((s) => s.trim() !== "");
  return {
    display_name: v.display_name.trim(),
    legal_name: blankToNull(v.legal_name),
    gst_treatment: v.gst_treatment,
    gstin,
    // With a GSTIN the server takes PAN and state from it.
    pan: gstin ? null : blankToNull(v.pan.toUpperCase()),
    state_code: gstin ? null : ((blankToNull(v.state_code) as PartyWrite["state_code"]) ?? null),
    is_customer: v.is_customer,
    is_vendor: v.is_vendor,
    email: blankToNull(v.email),
    phone: blankToNull(v.phone),
    billing_address: hasAddress
      ? {
          line1: a.line1.trim(),
          ...(blankToNull(a.line2) ? { line2: a.line2.trim() } : {}),
          city: a.city.trim(),
          ...(overseas
            ? { country: a.country.trim().toUpperCase() }
            : {
                country: "IN",
                ...(a.state_code ? { state_code: a.state_code as never } : {}),
                pincode: a.pincode.trim(),
              }),
        }
      : null,
  };
}

function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p className="text-destructive text-sm" id={`${id}-error`}>
          {error}
        </p>
      ) : (
        hint && <p className="text-muted-foreground text-xs">{hint}</p>
      )}
    </div>
  );
}

function TextField({
  id,
  label,
  error,
  hint,
  registration,
  ...input
}: {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string;
  registration: UseFormRegisterReturn;
} & Omit<React.ComponentProps<"input">, "id">) {
  return (
    <Field id={id} label={label} error={error} {...(hint ? { hint } : {})}>
      <Input
        id={id}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        {...input}
        {...registration}
      />
    </Field>
  );
}

export function PartyFormPage() {
  const { partyId } = useParams();
  const isNew = partyId === undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<{ kind: "error" | "saved"; text: string } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

  const party = useQuery({
    queryKey: ["party", partyId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}", {
          params: { path: { party_id: partyId ?? "" } },
        }),
      ),
    enabled: !isNew,
  });

  const form = useForm<FormValues>({ resolver: zodResolver(formSchema), defaultValues: EMPTY });
  const { register, handleSubmit, reset, setError, formState, control } = form;
  const treatment = useWatch({ control, name: "gst_treatment" });
  const errors = formState.errors;
  useEffect(() => {
    if (party.data) reset(toForm(party.data));
  }, [party.data, reset]);

  const save = useMutation({
    mutationFn: async (values: FormValues) => {
      const body = toApi(values);
      if (isNew) {
        return unwrap(
          await api.POST("/api/v1/parties", {
            body,
            headers: { "Idempotency-Key": idempotencyKey },
          }),
        );
      }
      return unwrap(
        await api.PATCH("/api/v1/parties/{party_id}", {
          params: { path: { party_id: partyId } },
          body,
          headers: { "If-Match": ifMatch(party.data?.version ?? 0) },
        }),
      );
    },
    onSuccess: (saved) => {
      setIdempotencyKey(newIdempotencyKey());
      queryClient.setQueryData(["party", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      setMessage({ kind: "saved", text: "Saved." });
      if (isNew) void navigate(`/parties/${saved.id}`, { replace: true });
      else reset(toForm(saved));
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "stale_version") {
        setMessage({
          kind: "error",
          text: "Someone else changed this party since you opened it. Reload to see their version.",
        });
        return;
      }
      const text = applyServerErrors(error, setError, FIELDS);
      setMessage(text ? { kind: "error", text } : null);
    },
  });

  const archive = useMutation({
    mutationFn: async (active: boolean) =>
      unwrap(
        await api.PATCH("/api/v1/parties/{party_id}", {
          params: { path: { party_id: partyId ?? "" } },
          body: { is_active: active },
          headers: { "If-Match": ifMatch(party.data?.version ?? 0) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["party", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      setMessage({ kind: "saved", text: saved.is_active ? "Restored." : "Archived." });
    },
    onError: (error) => {
      setMessage({ kind: "error", text: error.message });
    },
  });

  if (!isNew && party.error) return <ErrorState error={party.error} />;
  if (!isNew && !party.data) return <Skeleton className="h-96 w-full" />;

  const needsGstin = NEEDS_GSTIN.has(treatment);
  const overseas = treatment === "OVERSEAS";

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/parties">
          <ArrowLeft aria-hidden /> Parties
        </Link>
      </Button>
      <PageHeader
        title={isNew ? "New party" : (party.data?.display_name ?? "")}
        description={
          !isNew && party.data && !party.data.is_active
            ? "Archived: hidden from new documents."
            : undefined
        }
        actions={
          !isNew &&
          party.data && (
            <Button
              variant="outline"
              disabled={archive.isPending}
              onClick={() => {
                archive.mutate(!party.data.is_active);
              }}
            >
              {party.data.is_active ? "Archive" : "Restore"}
            </Button>
          )
        }
      />

      {message && (
        <Alert variant={message.kind === "error" ? "destructive" : "default"} className="mb-4">
          {message.kind === "error" ? <AlertCircle aria-hidden /> : <CheckCircle2 aria-hidden />}
          <AlertDescription className="flex flex-wrap items-center gap-2">
            {message.text}
            {message.text.startsWith("Someone else") && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setMessage(null);
                  void party.refetch();
                }}
              >
                Reload
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

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
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>Details</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <TextField
              id="display_name"
              label="Name"
              error={errors.display_name?.message}
              registration={register("display_name")}
            />
            <TextField
              id="legal_name"
              label="Legal name"
              hint="As on the GST registration, if different."
              error={errors.legal_name?.message}
              registration={register("legal_name")}
            />
            <fieldset className="grid gap-2 sm:col-span-2">
              <legend className="mb-2 text-sm font-medium">This party is a</legend>
              <div className="flex gap-6">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" {...register("is_customer")} /> Customer (we bill them)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" {...register("is_vendor")} /> Vendor (we buy from them)
                </label>
              </div>
              {errors.is_customer && (
                <p className="text-destructive text-sm">{errors.is_customer.message}</p>
              )}
            </fieldset>
            <TextField
              id="email"
              label="Email"
              type="email"
              error={errors.email?.message}
              registration={register("email")}
            />
            <TextField
              id="phone"
              label="Phone"
              type="tel"
              error={errors.phone?.message}
              registration={register("phone")}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <h2>GST</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="gst_treatment" label="GST status" error={errors.gst_treatment?.message}>
              <NativeSelect id="gst_treatment" {...register("gst_treatment")}>
                {TREATMENTS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            {needsGstin ? (
              <TextField
                id="gstin"
                label="GSTIN"
                className="font-mono uppercase"
                autoComplete="off"
                maxLength={15}
                hint="PAN and state are taken from it."
                error={errors.gstin?.message}
                registration={register("gstin")}
              />
            ) : (
              <>
                <TextField
                  id="pan"
                  label="PAN"
                  className="font-mono uppercase"
                  maxLength={10}
                  error={errors.pan?.message}
                  registration={register("pan")}
                />
                {!overseas && (
                  <Field id="state_code" label="State" error={errors.state_code?.message}>
                    <NativeSelect id="state_code" {...register("state_code")}>
                      <option value="">–</option>
                      {STATE_OPTIONS.map((s) => (
                        <option key={s.code} value={s.code}>
                          {s.name}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              <h2>Billing address</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <TextField
              id="address-line1"
              label="Address line 1"
              error={errors.billing_address?.line1?.message}
              registration={register("billing_address.line1")}
            />
            <TextField
              id="address-line2"
              label="Address line 2"
              error={errors.billing_address?.line2?.message}
              registration={register("billing_address.line2")}
            />
            <TextField
              id="address-city"
              label="City"
              error={errors.billing_address?.city?.message}
              registration={register("billing_address.city")}
            />
            {overseas ? (
              <TextField
                id="address-country"
                label="Country code"
                hint="Two letters, e.g. AE."
                maxLength={2}
                className="uppercase"
                error={errors.billing_address?.country?.message}
                registration={register("billing_address.country")}
              />
            ) : (
              <>
                <Field
                  id="address-state"
                  label="State"
                  error={errors.billing_address?.state_code?.message}
                >
                  <NativeSelect id="address-state" {...register("billing_address.state_code")}>
                    <option value="">–</option>
                    {STATE_OPTIONS.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.name}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <TextField
                  id="address-pincode"
                  label="PIN code"
                  inputMode="numeric"
                  maxLength={6}
                  error={errors.billing_address?.pincode?.message}
                  registration={register("billing_address.pincode")}
                />
              </>
            )}
          </CardContent>
        </Card>

        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {isNew ? "Create party" : "Save changes"}
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to="/parties">Cancel</Link>
          </Button>
        </div>
      </form>
    </>
  );
}
