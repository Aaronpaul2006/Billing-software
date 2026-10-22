import { useQuery } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { Body, Button, Card, ErrorView, Loading } from "@/components/ui";
import { compareMoney, formatInr, formatQty } from "@/lib/money";
import { space, useColors } from "@/theme";

const STATUS: Record<string, string> = {
  PLANNED: "Planned",
  ACTIVE: "Active",
  ON_HOLD: "On hold",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
};

function Row({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  const c = useColors();
  return (
    <View style={styles.row}>
      <Text style={[styles.text, { color: c.text }]}>{label}</Text>
      <Text style={[styles.text, { color: tone === "danger" ? c.danger : c.text }]}>{value}</Text>
    </View>
  );
}

export function ProjectScreen() {
  const c = useColors();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } }),
      ),
  });
  const money = useQuery({
    queryKey: ["reports", "projects", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reports/projects/{project_id}", {
          params: { path: { project_id: id } },
        }),
      ),
  });
  const boq = useQuery({
    queryKey: ["boq-progress", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/boq-progress", {
          params: { path: { project_id: id } },
        }),
      ),
  });

  const error = project.error ?? money.error;
  if (error) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <ErrorView
          error={error}
          onRetry={() => {
            void project.refetch();
            void money.refetch();
          }}
        />
      </View>
    );
  }
  if (!project.data || !money.data) return <Loading />;
  const p = project.data;
  const m = money.data;
  const loss = compareMoney(m.margin, "0") === -1;
  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.page}
      refreshControl={
        <RefreshControl
          refreshing={money.isRefetching}
          onRefresh={() => {
            void project.refetch();
            void money.refetch();
            void boq.refetch();
          }}
        />
      }
    >
      <Stack.Screen options={{ title: p.code }} />
      <Card>
        <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
          {p.name}
        </Text>
        <Body muted>
          {p.code} · {STATUS[p.status] ?? p.status} · {p.client_name}
        </Body>
      </Card>
      <Button
        label={`Unpaid bills of ${p.client_name}`}
        variant="secondary"
        onPress={() => {
          router.push(`/clients/${p.client_party_id}`);
        }}
      />
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Money
      </Text>
      <Card>
        {m.contract_value !== null && (
          <Row label="Contract value" value={formatInr(m.contract_value)} />
        )}
        <Row label="Billed (before GST)" value={formatInr(m.billed_taxable)} />
        <Row label="Retention held" value={formatInr(m.retention_held)} />
        <Row label="TDS deducted" value={formatInr(m.tds_deducted)} />
        <Row label="Advance recovered" value={formatInr(m.advance_recovered)} />
        <Row label="Outstanding" value={formatInr(m.outstanding)} />
        <Row label="Cost" value={formatInr(m.cost)} />
        <Row label="Margin" value={formatInr(m.margin)} {...(loss ? { tone: "danger" } : {})} />
      </Card>
      {boq.data && boq.data.results.length > 0 && (
        <>
          <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
            BOQ progress
          </Text>
          <Card>
            <Row
              label="Billed of the contract"
              value={
                boq.data.totals.progress_pct === null
                  ? "–"
                  : `${formatQty(boq.data.totals.progress_pct)} %`
              }
            />
            {boq.data.results.map((r) => (
              <Row
                key={r.boq_item_id}
                label={`${r.item_code} ${r.description}`}
                value={r.progress_pct === null ? "–" : `${formatQty(r.progress_pct)} %`}
                {...(r.balance_qty.startsWith("-") ? { tone: "danger" as const } : {})}
              />
            ))}
          </Card>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  title: { fontSize: 18, fontWeight: "700" },
  heading: { fontSize: 18, fontWeight: "700", marginTop: space.sm },
  row: { flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 2 },
  text: { fontSize: 15, fontVariant: ["tabular-nums"], flexShrink: 1 },
});
