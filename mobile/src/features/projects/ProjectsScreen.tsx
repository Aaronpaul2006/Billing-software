import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { FlatList, RefreshControl, StyleSheet, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { ListRow } from "@/components/list";
import { Body, ErrorView, Loading } from "@/components/ui";
import { compareMoney, formatInr } from "@/lib/money";
import { space, useColors } from "@/theme";

/** Every project with what it billed, what is owed and the margin so far. */
export function ProjectsScreen() {
  const c = useColors();
  const router = useRouter();
  const report = useQuery({
    queryKey: ["reports", "projects"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/projects")).results,
  });
  if (report.error) {
    return (
      <View style={[styles.pad, { backgroundColor: c.background }]}>
        <ErrorView error={report.error} onRetry={() => void report.refetch()} />
      </View>
    );
  }
  if (!report.data) return <Loading />;
  return (
    <FlatList
      style={{ backgroundColor: c.background }}
      data={report.data}
      keyExtractor={(p) => p.project_id}
      ListEmptyComponent={
        <View style={styles.pad}>
          <Body muted>No projects yet.</Body>
        </View>
      }
      refreshControl={
        <RefreshControl refreshing={report.isRefetching} onRefresh={() => void report.refetch()} />
      }
      renderItem={({ item: p }) => {
        const loss = compareMoney(p.margin, "0") === -1;
        return (
          <ListRow
            title={p.name}
            subtitle={`${p.code} · billed ${formatInr(p.billed_taxable)}`}
            amount={formatInr(p.outstanding)}
            note={`margin ${formatInr(p.margin)}`}
            noteTone={loss ? "danger" : "muted"}
            accessibilityLabel={`${p.name}, ${formatInr(p.outstanding)} outstanding`}
            onPress={() => {
              router.push(`/projects/${p.project_id}`);
            }}
          />
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  pad: { padding: space.lg },
});
