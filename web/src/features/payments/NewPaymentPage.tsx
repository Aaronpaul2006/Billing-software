import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { api, newIdempotencyKey, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { isoDate } from "@/features/dashboard/periods";
import { applyServerErrors } from "@/lib/forms";
import { cleanMoneyInput, MONEY_INPUT, toPaise } from "@/lib/money";

import { allocationProblems, toAllocationItems, useOpenItems } from "./allocations";
import type { Allocations } from "./allocations";
import { AllocationTable } from "./AllocationTable";
import { MODE_LABELS } from "./modes";

type Mode = components["schemas"]["PaymentModeEnum"];

/** Record money received, allocating it to what the client owes in the same step. */
export function NewPaymentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [party, setParty] = useState<PickedParty | null>(null);
  const [projectId, setProjectId] = useState("");
  const [date, setDate] = useState(() => isoDate(new Date()));
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState<Mode>("BANK_TRANSFER");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [allocations, setAllocations] = useState<Allocations>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const partyId = party?.id ?? "";
  const open = useOpenItems(partyId, true);
  const projects = useQuery({
    queryKey: ["projects", "of", partyId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects", {
          params: { query: { client_party_id: partyId, limit: 100, ordering: "code" } },
        }),
      ).results,
    enabled: partyId !== "",
  });

  const cleanAmount = cleanMoneyInput(amount);
  const amountOk = MONEY_INPUT.test(cleanAmount) && (toPaise(cleanAmount) ?? 0n) > 0n;
  const problems = amountOk ? allocationProblems(open.data ?? [], allocations, cleanAmount) : [];

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payments", {
          body: {
            party_id: partyId,
            project_id: projectId || null,
            payment_date: date,
            amount: cleanAmount,
            mode,
            reference: reference.trim() || null,
            notes: notes.trim() || null,
            allocations: toAllocationItems(allocations),
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (payment) => {
      setKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: ["payments"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["open-items"] });
      void navigate(`/payments/${payment.id}`);
    },
    onError: (e) => {
      const fieldErrors: Record<string, string> = {};
      const text = applyServerErrors(
        e,
        (field, error) => {
          fieldErrors[field] = error.message ?? "";
        },
        ["party_id", "payment_date", "amount", "mode", "reference", "project_id"],
      );
      setErrors(fieldErrors);
      setMessage(text);
    },
  });

  return (
    <>
      <Breadcrumbs
        items={[{ label: "Payments", to: "/payments" }, { label: "Record a payment" }]}
      />
      <PageHeader title="Record payment" />
      <form
        noValidate
        className="grid max-w-4xl gap-6"
        onSubmit={(e) => {
          e.preventDefault();
          setMessage(null);
          const local: Record<string, string> = {};
          if (!partyId) local.party_id = "Choose the client.";
          if (!amountOk) local.amount = "An amount like 300000 or 3,00,000.50.";
          setErrors(local);
          if (Object.keys(local).length === 0 && problems.length === 0) save.mutate();
        }}
      >
        {message && (
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <Field id="party" label="Client" error={errors.party_id}>
              <PartyPicker
                id="party"
                value={party}
                invalid={!!errors.party_id}
                onChange={(picked) => {
                  setParty(picked);
                  setProjectId("");
                  setAllocations({});
                }}
              />
            </Field>
            <Field id="amount" label="Amount received (₹)" error={errors.amount}>
              <Input
                id="amount"
                inputMode="decimal"
                aria-invalid={!!errors.amount}
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                }}
              />
            </Field>
            <Field id="payment_date" label="Date" error={errors.payment_date}>
              <Input
                id="payment_date"
                type="date"
                value={date}
                onChange={(e) => {
                  setDate(e.target.value);
                }}
              />
            </Field>
            <Field id="mode" label="Mode" error={errors.mode}>
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
            <Field
              id="reference"
              label="Reference"
              hint="UTR or cheque number."
              error={errors.reference}
            >
              <Input
                id="reference"
                value={reference}
                onChange={(e) => {
                  setReference(e.target.value);
                }}
              />
            </Field>
            <Field id="project" label="Project" error={errors.project_id}>
              <NativeSelect
                id="project"
                disabled={!partyId}
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                }}
              >
                <option value="">Any</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <div className="sm:col-span-3">
              <Field id="notes" label="Notes">
                <Input
                  id="notes"
                  value={notes}
                  onChange={(e) => {
                    setNotes(e.target.value);
                  }}
                />
              </Field>
            </div>
          </CardContent>
        </Card>

        {partyId && (
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Allocate to</h2>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <AllocationTable
                items={open.data ?? []}
                allocations={allocations}
                onChange={setAllocations}
                available={amountOk ? cleanAmount : ""}
                isLoading={open.isPending}
                error={open.error}
              />
              {problems.length > 0 && (
                <ul className="text-destructive text-sm">
                  {problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending || problems.length > 0}>
            Record payment
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to="/payments">Cancel</Link>
          </Button>
        </div>
      </form>
    </>
  );
}
