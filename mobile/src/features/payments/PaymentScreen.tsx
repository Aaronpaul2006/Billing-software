import { useQuery } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { Badge } from "@/components/list";
import { Body, Card, ErrorView, Loading } from "@/components/ui";
import { formatDate } from "@/features/documents/labels";
import { compareMoney, formatInr } from "@/lib/money";
import { space, useColors } from "@/theme";

import { MODE_LABELS } from "./labels";

/** One payment and the bills it settled. */
export function PaymentScreen() {
  const c = useColors();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const payment = useQuery({
    queryKey: ["payment", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/payments/{payment_id}", { params: { path: { payment_id: id } } }),
      ),
  });
  if (payment.error) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <ErrorView error={payment.error} onRetry={() => void payment.refetch()} />
      </View>
    );
  }
  if (!payment.data) return <Loading />;
  const p = payment.data;
  const voided = p.status === "VOIDED";
  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.page}
      refreshControl={
        <RefreshControl
          refreshing={payment.isRefetching}
          onRefresh={() => void payment.refetch()}
        />
      }
    >
      <Stack.Screen options={{ title: "Payment" }} />
      <Card>
        <View style={styles.titleRow}>
          <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
            {formatInr(p.amount)}
          </Text>
          {voided && <Badge text="Voided" tone="muted" />}
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Client ${p.party_name}`}
          onPress={() => {
            router.push(`/clients/${p.party_id}`);
          }}
        >
          <Text style={[styles.link, { color: c.primary }]}>{p.party_name}</Text>
        </Pressable>
        <Body muted>
          {formatDate(p.payment_date)} · {MODE_LABELS[p.mode]}
          {p.reference ? ` · ${p.reference}` : ""}
        </Body>
        {p.project_name && <Body muted>Project: {p.project_name}</Body>}
        {voided && p.void_reason && <Body muted>Voided: {p.void_reason}</Body>}
        {p.notes && <Body muted>{p.notes}</Body>}
      </Card>
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Settled
      </Text>
      <Card>
        {p.allocations.length === 0 && <Body muted>Not allocated to any bill yet.</Body>}
        {p.allocations.map((a) => {
          const documentId = a.document_id;
          const label = a.doc_number ?? (a.retention_release_id ? "Retention release" : "Bill");
          return (
            <Pressable
              key={a.id}
              accessibilityRole={documentId ? "button" : undefined}
              accessibilityLabel={`${label}, ${formatInr(a.amount)}`}
              disabled={!documentId}
              onPress={() => {
                if (documentId) router.push(`/documents/${documentId}`);
              }}
              style={styles.row}
            >
              <Text style={[styles.text, { color: documentId ? c.primary : c.text }]}>{label}</Text>
              <Text style={[styles.text, { color: c.text }]}>{formatInr(a.amount)}</Text>
            </Pressable>
          );
        })}
        {!voided && compareMoney(p.unallocated, "0") === 1 && (
          <View style={styles.row}>
            <Text style={[styles.text, { color: c.warn }]}>Not allocated</Text>
            <Text style={[styles.text, { color: c.warn }]}>{formatInr(p.unallocated)}</Text>
          </View>
        )}
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  titleRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  title: { fontSize: 22, fontWeight: "700", fontVariant: ["tabular-nums"] },
  link: { fontSize: 16, fontWeight: "600" },
  heading: { fontSize: 18, fontWeight: "700", marginTop: space.sm },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  text: { fontSize: 15, fontVariant: ["tabular-nums"] },
});
