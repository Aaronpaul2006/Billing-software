import { useQuery } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { Linking, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { Badge, ListRow } from "@/components/list";
import { Body, Button, Card, ErrorView, Loading } from "@/components/ui";
import {
  DOC_TYPE_LABELS,
  formatDate,
  RECEIVABLE_TYPES,
  standing,
} from "@/features/documents/labels";
import { canRecordPayments } from "@/lib/actions";
import { formatInr, sumMoney } from "@/lib/money";
import { space, useColors } from "@/theme";

/** A client: how to reach them, and every bill they have not paid in full. */
export function ClientScreen() {
  const c = useColors();
  const router = useRouter();
  const session = useSession();
  const { id } = useLocalSearchParams<{ id: string }>();
  const party = useQuery({
    queryKey: ["party", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/parties/{party_id}", { params: { path: { party_id: id } } })),
  });
  const open = useQuery({
    queryKey: ["documents", "open", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents", {
          params: {
            query: {
              party_id: id,
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

  if (party.error) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <ErrorView error={party.error} onRetry={() => void party.refetch()} />
      </View>
    );
  }
  if (!party.data) return <Loading />;
  const p = party.data;
  const owed = open.data ? sumMoney(open.data.map((d) => d.totals.outstanding)) : null;
  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.page}
      refreshControl={
        <RefreshControl
          refreshing={party.isRefetching || open.isRefetching}
          onRefresh={() => {
            void party.refetch();
            void open.refetch();
          }}
        />
      }
    >
      <Stack.Screen options={{ title: p.display_name }} />
      <Card>
        <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
          {p.display_name}
        </Text>
        {p.gstin && <Body muted>GSTIN {p.gstin}</Body>}
        {p.phone && <Body muted>{p.phone}</Body>}
        {p.email && <Body muted>{p.email}</Body>}
      </Card>
      {canRecordPayments(session.role) && (
        <Button
          label="Record a payment"
          onPress={() => {
            router.push({ pathname: "/payments/new", params: { party: p.id } });
          }}
        />
      )}
      {(p.phone ?? p.email) && (
        <View style={styles.actions}>
          {p.phone && (
            <View style={styles.action}>
              <Button
                label="Call"
                variant="secondary"
                accessibilityLabel={`Call ${p.display_name}`}
                onPress={() => void Linking.openURL(`tel:${p.phone ?? ""}`)}
              />
            </View>
          )}
          {p.email && (
            <View style={styles.action}>
              <Button
                label="Email"
                variant="secondary"
                accessibilityLabel={`Email ${p.display_name}`}
                onPress={() => void Linking.openURL(`mailto:${p.email ?? ""}`)}
              />
            </View>
          )}
        </View>
      )}
      <View style={styles.owedRow}>
        <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
          Unpaid bills
        </Text>
        {owed !== null && (
          <Text style={[styles.heading, { color: c.text }]}>{formatInr(owed)}</Text>
        )}
      </View>
      {open.error ? (
        <ErrorView error={open.error} onRetry={() => void open.refetch()} />
      ) : !open.data ? (
        <Loading />
      ) : open.data.length === 0 ? (
        <Body muted>Nothing unpaid.</Body>
      ) : (
        <Card style={styles.list}>
          {open.data.map((d) => {
            const state = standing(d);
            return (
              <ListRow
                key={d.id}
                title={d.doc_number ?? DOC_TYPE_LABELS[d.doc_type]}
                subtitle={`${formatDate(d.doc_date)}${d.due_date ? ` · due ${formatDate(d.due_date)}` : ""}`}
                amount={formatInr(d.totals.outstanding)}
                note={`of ${formatInr(d.totals.net_receivable)}`}
                badge={<Badge text={state.text} tone={state.tone} />}
                onPress={() => {
                  router.push(`/documents/${d.id}`);
                }}
              />
            );
          })}
        </Card>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  title: { fontSize: 18, fontWeight: "700" },
  heading: { fontSize: 18, fontWeight: "700" },
  actions: { flexDirection: "row", gap: space.md },
  action: { flex: 1 },
  owedRow: { flexDirection: "row", justifyContent: "space-between", marginTop: space.sm },
  list: { padding: 0, overflow: "hidden" },
});
