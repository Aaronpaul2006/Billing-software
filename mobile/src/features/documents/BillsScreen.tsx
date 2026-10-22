import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { Badge, CursorList, ListRow } from "@/components/list";
import { Choice, TextField } from "@/components/ui";
import { formatInr } from "@/lib/money";
import { space } from "@/theme";

import { DOC_TYPE_LABELS, formatDate, RECEIVABLE_TYPES, standing } from "./labels";

type View_ = "UNPAID" | "ALL" | "DRAFTS";

const VIEWS: readonly { value: View_; label: string }[] = [
  { value: "UNPAID", label: "Unpaid" },
  { value: "ALL", label: "All" },
  { value: "DRAFTS", label: "Drafts" },
];

/** What each view asks the API for. Unpaid: oldest first, to chase them in order. */
function filters(view: View_) {
  switch (view) {
    case "UNPAID":
      return {
        status: ["ISSUED"],
        doc_type: [...RECEIVABLE_TYPES],
        payment_state: "OPEN" as const,
        ordering: "doc_date,doc_number",
      };
    case "DRAFTS":
      return { status: ["DRAFT"], ordering: "-created_at" };
    case "ALL":
      return { ordering: "-doc_date,-doc_number" };
  }
}

export function BillsScreen() {
  const router = useRouter();
  const [view, setView] = useState<View_>("UNPAID");
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const query = { ...filters(view), ...(search ? { q: search } : {}), limit: 30 };
  return (
    <CursorList
      testID="bills"
      queryKey={["documents", "list", query]}
      fetchPage={async (cursor) =>
        unwrap(
          await api.GET("/api/v1/documents", {
            params: { query: { ...query, ...(cursor ? { cursor } : {}) } },
          }),
        )
      }
      empty={
        search
          ? `Nothing found for “${search}”.`
          : view === "UNPAID"
            ? "Nothing unpaid."
            : view === "DRAFTS"
              ? "No drafts."
              : "No bills yet."
      }
      header={
        <View style={styles.header}>
          <Choice label="Show" options={VIEWS} value={view} onChange={setView} />
          <TextField
            label="Search by number"
            value={typed}
            onChangeText={setTyped}
            onSubmitEditing={() => {
              setSearch(typed.trim());
            }}
            returnKeyType="search"
            autoCapitalize="characters"
            autoCorrect={false}
          />
        </View>
      }
      renderItem={(d) => {
        const state = standing(d);
        const open = RECEIVABLE_TYPES.includes(d.doc_type) && d.status === "ISSUED";
        return (
          <ListRow
            title={d.doc_number ?? `${DOC_TYPE_LABELS[d.doc_type]} (draft)`}
            subtitle={`${d.party_name} · ${formatDate(d.doc_date)}`}
            amount={formatInr(d.totals.grand_total)}
            note={open && state.text !== "Paid" ? `${formatInr(d.totals.outstanding)} due` : null}
            noteTone={state.tone === "danger" ? "danger" : "muted"}
            badge={<Badge text={state.text} tone={state.tone} />}
            accessibilityLabel={`${d.doc_number ?? "Draft"}, ${d.party_name}`}
            onPress={() => {
              router.push(`/documents/${d.id}`);
            }}
          />
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  header: { gap: space.md },
});
