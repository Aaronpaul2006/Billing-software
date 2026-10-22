import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/errors";
import { blankToNull, ifMatch } from "@/lib/forms";

type Tenant = components["schemas"]["Tenant"];
type TimeZone = components["schemas"]["TimezoneEnum"];

const INDIA = "Asia/Kolkata";

/** India first, then every zone the browser knows (and the company's current one). */
function timeZoneChoices(current: string): string[] {
  let known: string[] = [];
  try {
    known = Intl.supportedValuesOf("timeZone");
  } catch {
    // an older browser: India and the current zone are enough
  }
  const others = new Set([current, ...known]);
  others.delete(INDIA);
  return [INDIA, ...[...others].sort()];
}

function CompanyForm({ tenant }: { tenant: Tenant }) {
  const queryClient = useQueryClient();
  const [legalName, setLegalName] = useState(tenant.legal_name);
  const [tradeName, setTradeName] = useState(tenant.trade_name ?? "");
  const [pan, setPan] = useState(tenant.pan ?? "");
  const [timeZone, setTimeZone] = useState<string>(tenant.timezone);
  const [zones] = useState(() => timeZoneChoices(tenant.timezone));
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tenant", {
          body: {
            legal_name: legalName.trim(),
            trade_name: blankToNull(tradeName),
            pan: blankToNull(pan.toUpperCase()),
            timezone: timeZone as TimeZone, // the server checks it is a real zone
          },
          headers: { "If-Match": ifMatch(tenant.version) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["tenant"], saved);
      void queryClient.invalidateQueries({ queryKey: ["me"] }); // the company switcher shows the name
      setNotice({ ok: true, text: "Saved." });
    },
    onError: (e) => {
      setNotice({
        ok: false,
        text:
          e instanceof ApiError && e.code === "stale_version"
            ? "Someone else changed the company details. Reload the page."
            : e instanceof ApiError && e.problem.errors?.length
              ? e.problem.errors.map((x) => x.message).join(" ")
              : errorMessage(e),
      });
    },
  });
  return (
    <form
      className="grid max-w-xl gap-4"
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
        <CardContent className="grid gap-4">
          <Field id="legal_name" label="Legal name">
            <Input
              id="legal_name"
              value={legalName}
              onChange={(e) => {
                setLegalName(e.target.value);
              }}
            />
          </Field>
          <Field id="trade_name" label="Trade name" hint="If you trade under another name.">
            <Input
              id="trade_name"
              value={tradeName}
              onChange={(e) => {
                setTradeName(e.target.value);
              }}
            />
          </Field>
          <Field id="pan" label="PAN">
            <Input
              id="pan"
              className="font-mono uppercase"
              maxLength={10}
              value={pan}
              onChange={(e) => {
                setPan(e.target.value);
              }}
            />
          </Field>
          <Field
            id="timezone"
            label="Time zone"
            hint="Decides what “today” is for document dates, due dates and reports."
          >
            <NativeSelect
              id="timezone"
              value={timeZone}
              onChange={(e) => {
                setTimeZone(e.target.value);
              }}
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z === INDIA ? `${z} (India)` : z}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <p className="text-muted-foreground text-sm">
            GSTINs and addresses are set per GST registration.
          </p>
        </CardContent>
      </Card>
      <div>
        <Button type="submit" disabled={save.isPending || legalName.trim() === ""}>
          Save
        </Button>
      </div>
    </form>
  );
}

export function CompanyPage() {
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant")),
  });
  return (
    <>
      <PageHeader title="Company" description="The business this account bills for." />
      {tenant.error ? (
        <ErrorState error={tenant.error} />
      ) : !tenant.data ? (
        <Skeleton className="h-48 w-full max-w-xl" />
      ) : (
        <CompanyForm key={tenant.data.id} tenant={tenant.data} />
      )}
    </>
  );
}
