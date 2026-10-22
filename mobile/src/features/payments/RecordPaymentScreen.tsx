import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { Body, Button, Card, Choice, ErrorView, Loading, Notice, TextField } from "@/components/ui";
import { formatDate, RECEIVABLE_TYPES } from "@/features/documents/labels";
import { canRecordPayments, newIdempotencyKey } from "@/lib/actions";
import { errorMessage } from "@/lib/errors";
import {
  cleanMoneyInput,
  compareMoney,
  fillInOrder,
  formatInr,
  MONEY_INPUT,
  subtractMoney,
  sumMoney,
} from "@/lib/money";
import { isoDate } from "@/lib/periods";
import { space, useColors } from "@/theme";

import { MODE_LABELS } from "./labels";

type Mode = components["schemas"]["PaymentModeEnum"];
type Day = "TODAY" | "YESTERDAY" | "OTHER";

const MODES = (Object.keys(MODE_LABELS) as Mode[]).map((value) => ({
  value,
  label: MODE_LABELS[value],
}));

const DAYS: readonly { value: Day; label: string }[] = [
  { value: "TODAY", label: "Today" },
  { value: "YESTERDAY", label: "Yesterday" },
  { value: "OTHER", label: "Another date" },
];

function referenceLabel(mode: Mode): string {
  if (mode === "CHEQUE") return "Cheque number";
  if (mode === "UPI" || mode === "BANK_TRANSFER") return "UTR / reference";
  return "Reference";
}

function paymentDate(day: Day, other: string, today = new Date()): string | null {
  if (day === "TODAY") return isoDate(today);
  if (day === "YESTERDAY") {
    return isoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1));
  }
  return /^\d{4}-\d{2}-\d{2}$/.test(other.trim()) ? other.trim() : null;
}

function problemText(error: unknown): string {
  if (error instanceof ApiError && error.problem.errors?.length) {
    return error.problem.errors.map((e) => e.message).join(" ");
  }
  return errorMessage(error);
}

/**
 * A payment from a client, spread over their unpaid bills oldest first
 * (`document` first when it came from a bill). Amounts are added in paise,
 * never floats; whatever is not allocated stays as an advance.
 */
export function RecordPaymentScreen() {
  const c = useColors();
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSession();
  const { party, document: first } = useLocalSearchParams<{ party: string; document?: string }>();
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState<Day>("TODAY");
  const [other, setOther] = useState("");
  const [mode, setMode] = useState<Mode>("UPI");
  const [reference, setReference] = useState("");
  const [manual, setManual] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey); // one per payment, resent on retry

  const client = useQuery({
    queryKey: ["party", party],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}", { params: { path: { party_id: party } } }),
      ),
  });
  const open = useQuery({
    queryKey: ["documents", "open", party],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents", {
          params: {
            query: {
              party_id: party,
              status: ["ISSUED"],
              doc_type: [...RECEIVABLE_TYPES],
              payment_state: "OPEN",
              ordering: "doc_date,doc_number",
              limit: 100,
            },
          },
        }),
      ).results,
  });

  const save = useMutation({
    mutationFn: async (body: components["schemas"]["PaymentCreate"]) =>
      unwrap(await api.POST("/api/v1/payments", { body, headers: { "Idempotency-Key": key } })),
    onSuccess: (created) => {
      for (const k of ["documents", "reports", "payments", "document"]) {
        void queryClient.invalidateQueries({ queryKey: [k] });
      }
      router.replace(`/payments/${created.id}`);
    },
    onError: (e) => {
      setProblem(problemText(e));
    },
  });

  if (!canRecordPayments(session.role)) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <Notice text="Your role cannot record payments." />
      </View>
    );
  }
  const error = client.error ?? open.error;
  if (error) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <ErrorView error={error} />
      </View>
    );
  }
  if (!client.data || !open.data) return <Loading />;

  const bills = [...open.data].sort((a, b) => (a.id === first ? -1 : b.id === first ? 1 : 0));
  const cleaned = cleanMoneyInput(amount);
  const amountOk = MONEY_INPUT.test(cleaned) && compareMoney(cleaned, "0") === 1;
  const auto = fillInOrder(
    amountOk ? cleaned : "0",
    bills.map((b) => b.totals.outstanding),
  );
  const shares = manual ?? auto;
  const allocated = sumMoney(shares);
  const left = amountOk && allocated !== null ? subtractMoney(cleaned, allocated) : null;

  const date = paymentDate(day, other);
  /** What to fix before sending, or null. The server checks all of it again. */
  const check = (): string | null => {
    if (!amountOk) return "Enter the amount received.";
    if (!date) return "Enter the date as YYYY-MM-DD.";
    if (allocated === null || left === null) return "Check the amounts for each bill.";
    if (left.startsWith("-")) return "The bills add up to more than the payment.";
    const over = bills.find((b, i) => compareMoney(shares[i] || "0", b.totals.outstanding) === 1);
    return over ? `More than ${over.doc_number ?? "the bill"} still owes.` : null;
  };

  const submit = () => {
    const issue = check();
    setProblem(issue);
    if (issue || !date) return;
    save.mutate({
      party_id: party,
      payment_date: date,
      amount: cleaned,
      mode,
      reference: reference.trim() || null,
      allocations: bills.flatMap((b, i) => {
        const share = cleanMoneyInput(shares[i] ?? "");
        return share && compareMoney(share, "0") === 1
          ? [{ document_id: b.id, amount: share }]
          : [];
      }),
    });
  };

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        style={{ backgroundColor: c.background }}
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
      >
        <Stack.Screen options={{ title: "Record a payment" }} />
        <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
          From {client.data.display_name}
        </Text>
        <TextField
          label="Amount received (₹)"
          value={amount}
          onChangeText={(v) => {
            setAmount(v);
            setManual(null); // a new amount is spread again, oldest first
          }}
          keyboardType="decimal-pad"
        />
        <Choice label="Date" options={DAYS} value={day} onChange={setDay} />
        {day === "OTHER" && (
          <TextField
            label="Date (YYYY-MM-DD)"
            value={other}
            onChangeText={setOther}
            keyboardType="numbers-and-punctuation"
          />
        )}
        <Choice label="Mode" options={MODES} value={mode} onChange={setMode} />
        <TextField
          label={referenceLabel(mode)}
          value={reference}
          onChangeText={setReference}
          autoCapitalize="characters"
          autoCorrect={false}
        />

        <View style={styles.headingRow}>
          <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
            Against bills
          </Text>
          {manual && (
            <Button
              label="Fill oldest first"
              variant="ghost"
              onPress={() => {
                setManual(null);
              }}
            />
          )}
        </View>
        {bills.length === 0 ? (
          <Body muted>No unpaid bills: the whole amount is kept as an advance.</Body>
        ) : (
          <Card>
            {bills.map((b, i) => {
              const name = b.doc_number ?? "Bill";
              return (
                <View key={b.id} style={[styles.bill, { borderColor: c.border }]}>
                  <View style={styles.fill}>
                    <Text style={[styles.billName, { color: c.text }]}>{name}</Text>
                    <Text style={[styles.small, { color: c.muted }]}>
                      {formatDate(b.doc_date)} · owes {formatInr(b.totals.outstanding)}
                    </Text>
                  </View>
                  <TextInput
                    accessibilityLabel={`Amount for ${name}`}
                    value={shares[i] ?? ""}
                    onChangeText={(v) => {
                      setManual(shares.map((s, j) => (j === i ? v : s)));
                    }}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={c.muted}
                    style={[styles.share, { color: c.text, borderColor: c.border }]}
                  />
                </View>
              );
            })}
          </Card>
        )}
        {amountOk && allocated !== null && left !== null && (
          <Body muted>
            Allocated {formatInr(allocated)}
            {compareMoney(left, "0") === 1 ? ` · kept as advance ${formatInr(left)}` : ""}
          </Body>
        )}
        {problem && <Notice text={problem} />}
        <Button label="Record payment" busy={save.isPending} onPress={submit} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { padding: space.lg, gap: space.md },
  title: { fontSize: 18, fontWeight: "700" },
  headingRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: space.sm,
  },
  heading: { fontSize: 18, fontWeight: "700" },
  bill: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  billName: { fontSize: 15, fontWeight: "600" },
  small: { fontSize: 13 },
  share: {
    width: 120,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: space.sm,
    paddingVertical: 6,
    fontSize: 15,
    textAlign: "right",
    fontVariant: ["tabular-nums"],
  },
});
