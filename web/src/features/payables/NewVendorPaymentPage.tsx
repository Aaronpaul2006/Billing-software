import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { Field } from "@/components/FormField";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { SaveBar } from "@/components/SaveBar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { isoDate } from "@/features/dashboard/periods";
import { MODE_LABELS } from "@/features/payments/modes";
import { formatDate } from "@/lib/dates";
import {
  cleanMoneyInput,
  compareMoney,
  fillInOrder,
  formatInr,
  MONEY_INPUT,
  subtractMoney,
  sumMoney,
} from "@/lib/money";

import { useOpenReleases, useOpenVendorBills } from "./api";

type Mode = components["schemas"]["PaymentModeEnum"];

interface Owed {
  id: string;
  kind: "bill" | "release";
  label: string;
  date: string;
  outstanding: string;
}

/**
 * Pay a vendor (Part B): the amount is set against their bills, oldest first;
 * each line can be changed. "Pay this vendor" on a bill opens it with the
 * vendor chosen (?vendor=&name=).
 */
export function NewVendorPaymentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [vendor, setVendor] = useState<PickedParty | null>(() => {
    const id = params.get("vendor");
    return id ? { id, name: params.get("name") ?? "" } : null;
  });
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(() => isoDate(new Date()));
  const [mode, setMode] = useState<Mode>("BANK_TRANSFER");
  const [reference, setReference] = useState("");
  const [lines, setLines] = useState<Record<string, string>>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [message, setMessage] = useState<string | null>(null);
  const bills = useOpenVendorBills(vendor?.id ?? "");
  const releases = useOpenReleases(vendor?.id ?? "");
  // their bills, then retention released to them, each still to pay
  const open: Owed[] = [
    ...(bills.data ?? []).map((b) => ({
      id: b.id,
      kind: "bill" as const,
      label: b.bill_number,
      date: b.bill_date,
      outstanding: b.outstanding,
    })),
    ...(releases.data ?? []).map((r) => ({
      id: r.id,
      kind: "release" as const,
      label: `Retention, ${r.wo_number}`,
      date: r.release_date,
      outstanding: r.outstanding,
    })),
  ];
  const kindOf = Object.fromEntries(open.map((o) => [o.id, o.kind]));

  const clean = cleanMoneyInput(amount);
  const amountOk = MONEY_INPUT.test(clean) && compareMoney(clean, "0") === 1;
  const fill = (value: string) => {
    const c = cleanMoneyInput(value);
    if (!MONEY_INPUT.test(c)) return;
    const shares = fillInOrder(
      c,
      open.map((b) => b.outstanding),
    );
    setLines(Object.fromEntries(open.map((b, i) => [b.id, shares[i] ?? ""])));
  };
  const allocated =
    sumMoney(
      Object.values(lines)
        .filter((v) => v !== "")
        .map(cleanMoneyInput),
    ) ?? "0.00";
  const left = amountOk ? subtractMoney(clean, allocated) : null;
  const over = left !== null && compareMoney(left, "0") === -1;

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/vendor-payments", {
          body: {
            vendor_party_id: vendor?.id ?? "",
            payment_date: date,
            amount: clean,
            mode,
            reference: reference.trim() || null,
            allocations: Object.entries(lines)
              .filter(([, v]) => v !== "" && compareMoney(cleanMoneyInput(v), "0") === 1)
              .map(([id, v]) =>
                kindOf[id] === "release"
                  ? { vendor_retention_release_id: id, amount: cleanMoneyInput(v) }
                  : { vendor_bill_id: id, amount: cleanMoneyInput(v) },
              ),
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (saved) => {
      setKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: ["vendor-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-retention-releases"] });
      void queryClient.invalidateQueries({ queryKey: ["vendor-payments"] });
      void queryClient.invalidateQueries({ queryKey: ["reports", "payables"] });
      void navigate(`/vendor-payments/${saved.id}`);
    },
    onError: (e) => {
      setMessage(
        e instanceof ApiError && e.problem.errors?.length
          ? e.problem.errors.map((x) => x.message).join(" ")
          : e.message,
      );
    },
  });

  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Payments to vendors", to: "/vendor-payments" },
          { label: "Pay a vendor" },
        ]}
      />
      <PageHeader
        title="Pay a vendor"
        description="Set the payment against their bills, oldest first; change any line."
      />
      <form
        noValidate
        aria-label="Pay a vendor"
        className="grid max-w-3xl gap-6"
        onSubmit={(e) => {
          e.preventDefault();
          setMessage(null);
          save.mutate();
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
            <Field id="vendor" label="Vendor">
              <PartyPicker
                id="vendor"
                role="vendor"
                value={vendor}
                onChange={(picked) => {
                  setVendor(picked);
                  setLines({});
                }}
              />
            </Field>
            <Field id="amount" label="Amount paid (₹)">
              <Input
                id="amount"
                inputMode="decimal"
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                  fill(e.target.value);
                }}
              />
            </Field>
            <Field id="date" label="Date">
              <Input
                id="date"
                type="date"
                value={date}
                onChange={(e) => {
                  setDate(e.target.value);
                }}
              />
            </Field>
            <Field id="mode" label="How">
              <NativeSelect
                id="mode"
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as Mode);
                }}
              >
                {Object.entries(MODE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field id="reference" label="Reference (optional)">
              <Input
                id="reference"
                placeholder="UTR, cheque number"
                value={reference}
                onChange={(e) => {
                  setReference(e.target.value);
                }}
              />
            </Field>
          </CardContent>
        </Card>
        {vendor && (
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Their bills still to pay</h2>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {open.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  {bills.isPending || releases.isPending
                    ? "Looking…"
                    : "Nothing owed: the payment stays as an advance."}
                </p>
              ) : (
                <ul aria-label="Bills to pay" className="grid gap-2">
                  {open.map((b) => (
                    <li
                      key={b.id}
                      className="flex flex-wrap items-center gap-3 rounded-md border p-2"
                    >
                      <span className="min-w-40 flex-1 text-sm">
                        <span className="font-medium">{b.label}</span>
                        <span className="text-muted-foreground">
                          {" "}
                          · {formatDate(b.date)} · owed <Money value={b.outstanding} />
                        </span>
                      </span>
                      <Input
                        aria-label={`Pay against ${b.label}`}
                        inputMode="decimal"
                        className="w-36"
                        value={lines[b.id] ?? ""}
                        onChange={(e) => {
                          setLines({ ...lines, [b.id]: e.target.value });
                        }}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
        <SaveBar
          status={
            amountOk && left !== null ? (
              over ? (
                <span className="text-destructive">The lines add up to more than the payment.</span>
              ) : (
                `Set against bills ${formatInr(allocated)}; left as an advance ${formatInr(left)}`
              )
            ) : undefined
          }
        >
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              void navigate("/vendor-payments");
            }}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !vendor || !amountOk || over}>
            Record payment
          </Button>
        </SaveBar>
      </form>
    </>
  );
}
