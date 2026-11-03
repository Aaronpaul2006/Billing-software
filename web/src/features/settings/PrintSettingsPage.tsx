import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError, fieldErrors } from "@/api/problem";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { uploadFile } from "@/features/files/upload";
import type { UploadStage } from "@/features/files/upload";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";

import { checkImage, IMAGE_TYPES, PRINT_SETTINGS_KEY, usePrintSettings } from "./printSettings";
import type { PrintSettings } from "./printSettings";

type Layout = PrintSettings["layout"];

const LAYOUTS: { value: Layout; title: string; text: string }[] = [
  {
    value: "SIMPLE",
    title: "Simple",
    text: "Item, quantity, rate and amount; the tax shown once in the totals. Easy for clients to read.",
  },
  {
    value: "DETAILED",
    title: "Detailed",
    text: "Every column (HSN/SAC, GST rate, discount), the tax breakup by rate and measurement rows.",
  },
];

/** A logo or signature: upload, preview, remove. `value` is the attachment id. */
function ImageField({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string | null;
  onChange: (attachmentId: string | null) => void;
}) {
  const [stage, setStage] = useState<UploadStage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const current = useQuery({
    queryKey: ["attachment", value],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/attachments/{attachment_id}", {
          params: { path: { attachment_id: value ?? "" } },
        }),
      ),
    enabled: value !== null,
    staleTime: 4 * 60_000, // the link lasts 5 minutes
  });
  const upload = useMutation({
    mutationFn: (file: File) => uploadFile(file, setStage),
    onSuccess: (attachment) => {
      onChange(attachment.id);
    },
    onError: (e) => {
      setProblem(e instanceof ApiError ? errorMessage(e) : e.message);
    },
    onSettled: () => {
      setStage(null);
    },
  });
  return (
    <Field id={id} label={label} hint={hint}>
      {value !== null ? (
        <div className="flex items-center gap-3">
          {current.data?.download_url ? (
            <img
              src={current.data.download_url}
              alt={label}
              className="h-16 max-w-48 rounded border object-contain p-1"
            />
          ) : (
            <span className="text-muted-foreground text-sm">Image saved</span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Remove the ${label.toLowerCase()}`}
            onClick={() => {
              onChange(null);
            }}
          >
            <X aria-hidden /> Remove
          </Button>
        </div>
      ) : stage ? (
        <p role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {stage === "sending" ? "Uploading…" : "Checking the file…"}
        </p>
      ) : (
        <input
          id={id}
          type="file"
          accept={IMAGE_TYPES.join(",")}
          className="text-sm file:mr-3 file:rounded-md file:border file:px-3 file:py-1"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            const reason = checkImage(file);
            setProblem(reason);
            if (!reason) upload.mutate(file);
          }}
        />
      )}
      {problem && <p className="text-destructive text-sm">{problem}</p>}
    </Field>
  );
}

type Text = Exclude<
  keyof PrintSettings,
  "layout" | "logo_attachment_id" | "signature_attachment_id" | "version"
>;

function PrintSettingsForm({ saved }: { saved: PrintSettings }) {
  const queryClient = useQueryClient();
  const [layout, setLayout] = useState<Layout>(saved.layout);
  const [logo, setLogo] = useState(saved.logo_attachment_id);
  const [signature, setSignature] = useState(saved.signature_attachment_id);
  const [text, setText] = useState<Record<Text, string>>({
    bank_account_name: saved.bank_account_name ?? "",
    bank_name: saved.bank_name ?? "",
    bank_account_number: saved.bank_account_number ?? "",
    bank_ifsc: saved.bank_ifsc ?? "",
    bank_branch: saved.bank_branch ?? "",
    upi_id: saved.upi_id ?? "",
    default_terms: saved.default_terms ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tenant/print-settings", {
          body: {
            layout,
            logo_attachment_id: logo,
            signature_attachment_id: signature,
            ...text, // blank means "not set": the server stores null
          },
          headers: { "If-Match": ifMatch(saved.version) },
        }),
      ),
    onSuccess: (next) => {
      queryClient.setQueryData(PRINT_SETTINGS_KEY, next);
      setErrors({});
      setNotice({ ok: true, text: "Saved. New PDFs use these settings." });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "stale_version") {
        setNotice({ ok: false, text: "Someone else changed these settings. Reload the page." });
        return;
      }
      const byField = e instanceof ApiError ? fieldErrors(e.problem) : {};
      setErrors(byField);
      setNotice({
        ok: false,
        text: Object.keys(byField).length ? "Check the marked fields." : errorMessage(e),
      });
    },
  });
  const input = (name: Text, label: string, extra: { hint?: string; className?: string } = {}) => (
    <Field
      id={name}
      label={label}
      error={errors[name]}
      {...(extra.hint ? { hint: extra.hint } : {})}
    >
      <Input
        id={name}
        className={extra.className}
        aria-invalid={errors[name] ? true : undefined}
        value={text[name]}
        onChange={(e) => {
          setText({ ...text, [name]: e.target.value });
        }}
      />
    </Field>
  );
  return (
    <form
      className="grid max-w-2xl gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        setNotice(null);
        save.mutate();
      }}
    >
      {notice && (
        <Alert variant={notice.ok ? "default" : "destructive"}>
          {notice.ok ? <CheckCircle2 aria-hidden /> : <AlertCircle aria-hidden />}
          <AlertDescription>{notice.text}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Layout</CardTitle>
        </CardHeader>
        <CardContent>
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="sr-only">Layout</legend>
            {LAYOUTS.map((l) => (
              <label
                key={l.value}
                className="has-checked:border-primary grid cursor-pointer gap-1 rounded-md border p-3 text-sm"
              >
                <span className="flex items-center gap-2 font-medium">
                  <input
                    type="radio"
                    name="layout"
                    value={l.value}
                    checked={layout === l.value}
                    onChange={() => {
                      setLayout(l.value);
                    }}
                  />
                  {l.title}
                </span>
                <span className="text-muted-foreground">{l.text}</span>
              </label>
            ))}
          </fieldset>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Logo and signature</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <ImageField
            id="logo"
            label="Logo"
            hint="PNG or JPEG, at most 1 MB. Printed at the top left."
            value={logo}
            onChange={setLogo}
          />
          <ImageField
            id="signature"
            label="Signature"
            hint="A scan of the signature (and stamp), printed above “Authorised signatory”."
            value={signature}
            onChange={setSignature}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Bank details and UPI</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {input("bank_account_name", "Account name")}
          {input("bank_name", "Bank")}
          {input("bank_account_number", "Account number", { className: "font-mono" })}
          {input("bank_ifsc", "IFSC", {
            className: "font-mono uppercase",
            hint: "Like SBIN0001234.",
          })}
          {input("bank_branch", "Branch")}
          {input("upi_id", "UPI ID", {
            hint: "Like name@okaxis. Bills then carry a QR code to pay the exact amount.",
          })}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Default terms</CardTitle>
        </CardHeader>
        <CardContent>
          <Field
            id="default_terms"
            label="Terms on new bills and quotations"
            error={errors.default_terms}
            hint="Filled in on every new bill; you can still change them on a bill."
          >
            <textarea
              id="default_terms"
              rows={4}
              className="border-input rounded-md border bg-transparent px-3 py-2 text-sm"
              value={text.default_terms}
              onChange={(e) => {
                setText({ ...text, default_terms: e.target.value });
              }}
            />
          </Field>
        </CardContent>
      </Card>
      <div>
        <Button type="submit" disabled={save.isPending}>
          Save
        </Button>
      </div>
    </form>
  );
}

export function PrintSettingsPage() {
  const settings = usePrintSettings();
  return (
    <>
      <PageHeader
        title="Bill printing"
        description="Logo, signature, bank details, UPI ID, default terms and the layout of your PDFs."
      />
      {settings.error ? (
        <ErrorState error={settings.error} />
      ) : !settings.data ? (
        <Skeleton className="h-96 w-full max-w-2xl" />
      ) : (
        <PrintSettingsForm saved={settings.data} />
      )}
    </>
  );
}
