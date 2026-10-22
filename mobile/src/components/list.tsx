import { useInfiniteQuery } from "@tanstack/react-query";
import type { QueryKey } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from "react-native";

import { space, useColors } from "@/theme";

import { Body, Button, ErrorView, Loading } from "./ui";

export type Tone = "default" | "muted" | "good" | "warn" | "danger";

export function Badge({ text, tone = "default" }: { text: string; tone?: Tone }) {
  const c = useColors();
  const color = {
    default: c.text,
    muted: c.muted,
    good: c.good,
    warn: c.warn,
    danger: c.danger,
  }[tone];
  return (
    <Text style={[styles.badge, { color, borderColor: color }]} numberOfLines={1}>
      {text}
    </Text>
  );
}

/** One line of a list: what it is on the left, the amount on the right. */
export function ListRow({
  title,
  subtitle,
  amount,
  note,
  noteTone = "muted",
  badge,
  onPress,
  accessibilityLabel,
}: {
  title: string;
  subtitle?: string | null;
  amount?: string;
  note?: string | null;
  noteTone?: Tone;
  badge?: ReactElement | null;
  onPress?: () => void;
  accessibilityLabel?: string;
}) {
  const c = useColors();
  const noteColor = {
    default: c.text,
    muted: c.muted,
    good: c.good,
    warn: c.warn,
    danger: c.danger,
  }[noteTone];
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={accessibilityLabel ?? title}
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        { borderColor: c.border, backgroundColor: pressed ? c.card : c.background },
      ]}
    >
      <View style={styles.left}>
        <View style={styles.titleLine}>
          <Text style={[styles.title, { color: c.text }]} numberOfLines={1}>
            {title}
          </Text>
          {badge}
        </View>
        {subtitle ? (
          <Text style={[styles.sub, { color: c.muted }]} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      <View style={styles.right}>
        {amount !== undefined && <Text style={[styles.amount, { color: c.text }]}>{amount}</Text>}
        {note ? <Text style={[styles.sub, { color: noteColor }]}>{note}</Text> : null}
      </View>
    </Pressable>
  );
}

interface Page<T> {
  results: T[];
  next_cursor: string | null;
}

/**
 * A list read page by page with the API's cursors: the next page loads when
 * the end comes into view (or with "Load more"); pull down to start again.
 */
export function CursorList<T extends { id: string }>({
  queryKey,
  fetchPage,
  renderItem,
  empty,
  header,
  testID,
}: {
  queryKey: QueryKey;
  fetchPage: (cursor: string | undefined) => Promise<Page<T>>;
  renderItem: (item: T) => ReactElement;
  empty: string;
  header?: ReactElement;
  testID?: string;
}) {
  const c = useColors();
  const list = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = list.data?.pages.flatMap((p) => p.results) ?? [];
  return (
    <FlatList
      testID={testID}
      style={{ backgroundColor: c.background }}
      data={items}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => renderItem(item)}
      ListHeaderComponent={header}
      ListHeaderComponentStyle={styles.header}
      ListEmptyComponent={
        list.error ? (
          <View style={styles.pad}>
            <ErrorView error={list.error} onRetry={() => void list.refetch()} />
          </View>
        ) : list.isPending ? (
          <Loading />
        ) : (
          <View style={styles.pad}>
            <Body muted>{empty}</Body>
          </View>
        )
      }
      ListFooterComponent={
        list.isFetchingNextPage ? (
          <Loading label="Loading more" />
        ) : list.hasNextPage ? (
          // Also loads by itself near the end; the button is for screen readers and slow lists.
          <Button label="Load more" variant="ghost" onPress={() => void list.fetchNextPage()} />
        ) : undefined
      }
      onEndReached={() => {
        if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
      }}
      onEndReachedThreshold={0.5}
      refreshControl={
        <RefreshControl
          refreshing={list.isRefetching && !list.isFetchingNextPage}
          onRefresh={() => void list.refetch()}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  badge: {
    fontSize: 11,
    fontWeight: "600",
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 4,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  left: { flex: 1, gap: 2 },
  titleLine: { flexDirection: "row", alignItems: "center", gap: space.sm },
  title: { fontSize: 15, fontWeight: "600", flexShrink: 1 },
  sub: { fontSize: 13 },
  right: { alignItems: "flex-end", gap: 2 },
  amount: { fontSize: 15, fontWeight: "600", fontVariant: ["tabular-nums"] },
  header: { padding: space.lg, gap: space.md },
  pad: { padding: space.lg },
});
