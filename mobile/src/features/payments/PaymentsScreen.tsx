import { useRouter } from "expo-router";

import { api, unwrap } from "@/api/client";
import { Badge, CursorList, ListRow } from "@/components/list";
import { formatDate } from "@/features/documents/labels";
import { compareMoney, formatInr } from "@/lib/money";

import { MODE_LABELS } from "./labels";

/** Payments received, newest first. */
export function PaymentsScreen() {
  const router = useRouter();
  const query = { ordering: "-payment_date", limit: 30 };
  return (
    <CursorList
      queryKey={["payments", "list", query]}
      fetchPage={async (cursor) =>
        unwrap(
          await api.GET("/api/v1/payments", {
            params: { query: { ...query, ...(cursor ? { cursor } : {}) } },
          }),
        )
      }
      empty="No payments yet."
      renderItem={(p) => {
        const voided = p.status === "VOIDED";
        const left = !voided && compareMoney(p.unallocated, "0") === 1;
        return (
          <ListRow
            title={p.party_name}
            subtitle={`${formatDate(p.payment_date)} · ${MODE_LABELS[p.mode]}${p.reference ? ` · ${p.reference}` : ""}`}
            amount={formatInr(p.amount)}
            note={left ? `${formatInr(p.unallocated)} not allocated` : null}
            noteTone="warn"
            badge={voided ? <Badge text="Voided" tone="muted" /> : null}
            accessibilityLabel={`${p.party_name}, ${formatInr(p.amount)} on ${formatDate(p.payment_date)}`}
            onPress={() => {
              router.push(`/payments/${p.id}`);
            }}
          />
        );
      }}
    />
  );
}
