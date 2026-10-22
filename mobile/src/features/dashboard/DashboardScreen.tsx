import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { Body, Card, Choice, ErrorView, Loading } from "@/components/ui";
import { compareMoney, formatInr } from "@/lib/money";
import { formatRange, PERIOD_LABELS, periodRange } from "@/lib/periods";
import type { PeriodKey } from "@/lib/periods";
import { space, useColors } from "@/theme";

type Book = "ALL" | "GST" | "NON_GST";
type Receivable = components["schemas"]["Receivable"];

const PERIODS = (Object.keys(PERIOD_LABELS) as PeriodKey[]).map((value) => ({
  value,
  label: PERIOD_LABELS[value],
}));

const BOOKS: readonly { value: Book; label: string }[] = [
  { value: "ALL", label: "All books" },
  { value: "GST", label: "GST" },
  { value: "NON_GST", label: "Non-GST" },
];

/** How many clients the dashboard lists; the rest are in the total. */
const TOP = 5;

function Stat({ title, value, note }: { title: string; value: string; note: string }) {
  const c = useColors();
  return (
    <Card style={styles.stat}>
      <Text style={[styles.statTitle, { color: c.muted }]}>{title}</Text>
      <Text style={[styles.statValue, { color: c.text }]}>{formatInr(value)}</Text>
      <Text style={[styles.note, { color: c.muted }]}>{note}</Text>
    </Card>
  );
}

function Summary({ from, to, book }: { from: string; to: string; book: Book }) {
  const summary = useQuery({
    queryKey: ["reports", "summary", { from, to, book }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/summary", { params: { query: { from, to, book } } })),
  });
  if (summary.error)
    return <ErrorView error={summary.error} onRetry={() => void summary.refetch()} />;
  if (!summary.data) return <Loading label="Loading the summary" />;
  const { current, previous } = summary.data;
  const before = (amount: string) => `Previous period: ${formatInr(amount)}`;
  return (
    <View style={styles.grid}>
      <Stat title="Billed" value={current.billed} note={before(previous.billed)} />
      <Stat title="Collected" value={current.collected} note={before(previous.collected)} />
      <Stat title="Outstanding" value={current.outstanding} note="Today, all periods" />
      <Stat title="Expenses" value={current.expenses} note={before(previous.expenses)} />
    </View>
  );
}

function ReceivableRow({ r }: { r: Receivable }) {
  const c = useColors();
  const router = useRouter();
  const overdue =
    compareMoney(r.days_90_plus, "0") === 1 ? `${formatInr(r.days_90_plus)} over 90 days` : null;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${r.display_name}, owes ${formatInr(r.total)}`}
      onPress={() => {
        router.push(`/clients/${r.party_id}`);
      }}
      style={[styles.row, { borderColor: c.border }]}
    >
      <View style={styles.rowText}>
        <Text style={[styles.name, { color: c.text }]} numberOfLines={1}>
          {r.display_name}
        </Text>
        <Text style={[styles.note, { color: overdue ? c.danger : c.muted }]}>
          {overdue ?? `${r.document_count} open ${r.document_count === 1 ? "bill" : "bills"}`}
        </Text>
      </View>
      <Text style={[styles.amount, { color: c.text }]}>{formatInr(r.total)}</Text>
    </Pressable>
  );
}

function Receivables({ book }: { book: Book }) {
  const c = useColors();
  const receivables = useQuery({
    queryKey: ["reports", "receivables", { book }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reports/receivables", { params: { query: { book } } })),
  });
  if (receivables.error)
    return <ErrorView error={receivables.error} onRetry={() => void receivables.refetch()} />;
  if (!receivables.data) return <Loading label="Loading receivables" />;
  const { results, totals } = receivables.data;
  if (results.length === 0) return <Body muted>Nothing outstanding.</Body>;
  // Largest first, compared exactly (paise), never as floats.
  const top = [...results].sort((a, b) => compareMoney(b.total, a.total) ?? 0).slice(0, TOP);
  return (
    <Card>
      {top.map((r) => (
        <ReceivableRow key={r.party_id} r={r} />
      ))}
      <View style={styles.totalRow}>
        <Text style={[styles.name, { color: c.text }]}>
          {results.length > TOP ? `All ${results.length} clients` : "Total"}
        </Text>
        <Text style={[styles.amount, { color: c.text }]}>{formatInr(totals.total)}</Text>
      </View>
    </Card>
  );
}

export function DashboardScreen() {
  const c = useColors();
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState<PeriodKey>("this_month");
  const [book, setBook] = useState<Book>("ALL");
  const [refreshing, setRefreshing] = useState(false);
  const { from, to } = periodRange(period, new Date());

  const refresh = async () => {
    setRefreshing(true);
    try {
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.page}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void refresh()} />}
    >
      <Choice label="Period" options={PERIODS} value={period} onChange={setPeriod} />
      <Choice label="Books" options={BOOKS} value={book} onChange={setBook} />
      <Body muted>{formatRange(from, to)}</Body>
      <Summary from={from} to={to} book={book} />
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Who owes you
      </Text>
      <Receivables book={book} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.md },
  stat: { flexBasis: "47%", flexGrow: 1 },
  statTitle: { fontSize: 13, fontWeight: "600" },
  statValue: { fontSize: 20, fontWeight: "700", fontVariant: ["tabular-nums"] },
  note: { fontSize: 12 },
  heading: { fontSize: 18, fontWeight: "700", marginTop: space.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowText: { flex: 1 },
  name: { fontSize: 15, fontWeight: "600" },
  amount: { fontSize: 15, fontWeight: "600", fontVariant: ["tabular-nums"] },
  totalRow: { flexDirection: "row", justifyContent: "space-between", paddingTop: space.sm },
});
