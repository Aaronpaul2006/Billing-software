import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError, fieldErrors } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";

type TallySettings = components["schemas"]["TallySettings"];
type Ledger = Exclude<keyof TallySettings, "version">;

const KEY = ["tenant", "tally-settings"] as const;

/** Each ledger, what it is for. */
const LEDGERS: { name: Ledger; label: string; hint?: string }[] = [
  { name: "sales_ledger", label: "Sales", hint: "The taxable value of every bill." },
  { name: "cgst_ledger", label: "CGST (output)" },
  { name: "sgst_ledger", label: "SGST (output)" },
  { name: "igst_ledger", label: "IGST (output)" },
  { name: "cess_ledger", label: "Cess (output)" },
  { name: "round_off_ledger", label: "Round off" },
  { name: "tds_ledger", label: "Income-tax TDS deducted by clients" },
  { name: "gst_tds_ledger", label: "GST TDS deducted by clients" },
  { name: "retention_ledger", label: "Retention held by clients" },
  { name: "advance_ledger", label: "Advances from clients", hint: "Recovered on bills." },
  {
    name: "bank_ledger",
    label: "Bank",
    hint: "Payments received by transfer, UPI, cheque or card.",
  },
  { name: "cash_ledger", label: "Cash", hint: "Payments received in cash." },
];

function TallyForm({ saved }: { saved: TallySettings }) {
  const queryClient = useQueryClient();
  const [names, setNames] = useState<Record<Ledger, string>>(
    () => Object.fromEntries(LEDGERS.map((l) => [l.name, saved[l.name]])) as Record<Ledger, string>,
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tenant/tally-settings", {
          body: Object.fromEntries(Object.entries(names).map(([k, v]) => [k, v.trim()])) as Record<
            Ledger,
            string
          >,
          headers: { "If-Match": ifMatch(saved.version) },
        }),
      ),
    onSuccess: (next) => {
      queryClient.setQueryData(KEY, next);
      setErrors({});
      setNotice({ ok: true, text: "Saved. The next Tally export uses these names." });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "stale_version") {
        setNotice({ ok: false, text: "Someone else changed these names. Reload the page." });
        return;
      }
      const byField = e instanceof ApiError ? fieldErrors(e.problem) : {};
      setErrors(byField);
      setNotice({
        ok: false,
        text: Object.keys(byField).length ? "Every ledger needs a name." : errorMessage(e),
      });
    },
  });
  return (
    <form
      aria-label="Tally ledger names"
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
      <p className="text-muted-foreground text-sm">
        Type each name exactly as the ledger is called in Tally: Tally matches them by name. Each
        client is posted to a ledger with the client&apos;s name.
      </p>
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {LEDGERS.map((l) => (
            <Field
              key={l.name}
              id={l.name}
              label={l.label}
              error={errors[l.name]}
              {...(l.hint ? { hint: l.hint } : {})}
            >
              <Input
                id={l.name}
                aria-invalid={errors[l.name] ? true : undefined}
                value={names[l.name]}
                onChange={(e) => {
                  setNames({ ...names, [l.name]: e.target.value });
                }}
              />
            </Field>
          ))}
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

export function TallySettingsPage() {
  const settings = useQuery({
    queryKey: KEY,
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant/tally-settings")),
  });
  return (
    <>
      <PageHeader
        title="Tally export"
        description="The ledger names written on vouchers exported to Tally (Exports, Tally)."
      />
      {settings.error ? (
        <ErrorState error={settings.error} />
      ) : !settings.data ? (
        <Skeleton className="h-96 w-full max-w-2xl" />
      ) : (
        <TallyForm saved={settings.data} />
      )}
    </>
  );
}
