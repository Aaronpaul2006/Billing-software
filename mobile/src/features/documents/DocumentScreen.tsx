import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { Badge } from "@/components/list";
import { Body, Button, Card, ErrorView, Loading, Notice } from "@/components/ui";
import { canIssueDocuments, canRecordPayments, ifMatch, newIdempotencyKey } from "@/lib/actions";
import { errorMessage } from "@/lib/errors";
import { compareMoney, formatInr, formatQty } from "@/lib/money";
import { space, useColors } from "@/theme";

import { DOC_TYPE_LABELS, documentTitle, formatDate, RECEIVABLE_TYPES, standing } from "./labels";
import { shareDocumentPdf, shareErrorText } from "./sharePdf";

type Document = components["schemas"]["Document"];
type Line = components["schemas"]["LineOut"];

function Amount({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  const c = useColors();
  const style = [styles.amountText, { color: c.text }, strong && styles.strong];
  return (
    <View style={styles.amountRow}>
      <Text style={style}>{label}</Text>
      <Text style={style}>{formatInr(value)}</Text>
    </View>
  );
}

/** Only the amounts that apply to this document (no rows of ₹0.00). */
function Totals({ d }: { d: Document }) {
  const t = d.totals;
  const some = (v: string) => compareMoney(v, "0") !== 0;
  const deductions = (
    [
      ["Retention", t.retention],
      ["Income-tax TDS", t.income_tax_tds],
      ["GST TDS", t.gst_tds],
      ["Advance recovered", t.advance_recovery],
    ] as const
  ).filter(([, v]) => some(v));
  const receivable = RECEIVABLE_TYPES.includes(d.doc_type) && d.status !== "DRAFT";
  return (
    <Card>
      <Amount label="Before GST" value={t.subtotal} />
      {some(t.cgst) && <Amount label="CGST" value={t.cgst} />}
      {some(t.sgst) && <Amount label="SGST" value={t.sgst} />}
      {some(t.igst) && <Amount label="IGST" value={t.igst} />}
      {some(t.cess) && <Amount label="Cess" value={t.cess} />}
      {some(t.round_off) && <Amount label="Round off" value={t.round_off} />}
      <Amount label="Total" value={t.grand_total} strong />
      {deductions.map(([label, value]) => (
        <Amount key={label} label={`Less ${label.toLowerCase()}`} value={value} />
      ))}
      {deductions.length > 0 && <Amount label="Net receivable" value={t.net_receivable} strong />}
      {receivable && (
        <>
          <Amount label="Settled" value={t.amount_settled ?? "0.00"} />
          <Amount label="Outstanding" value={t.outstanding} strong />
        </>
      )}
    </Card>
  );
}

function LineRow({ line, ra }: { line: Line; ra: boolean }) {
  const c = useColors();
  const unit = line.unit ? ` ${line.unit}` : "";
  return (
    <View style={[styles.line, { borderColor: c.border }]}>
      <Text style={[styles.lineTitle, { color: c.text }]}>{line.description}</Text>
      <View style={styles.amountRow}>
        <Text style={[styles.small, { color: c.muted }]}>
          {formatQty(line.quantity)}
          {unit} × {formatInr(line.rate)} · GST {formatQty(line.gst_rate)} %
        </Text>
        <Text style={[styles.amountText, { color: c.text }]}>{formatInr(line.taxable_value)}</Text>
      </View>
      {ra && line.up_to_date_qty !== null && (
        <Text style={[styles.small, { color: c.muted }]}>
          Previous {formatQty(line.prev_cumulative_qty)} · up to date{" "}
          {formatQty(line.up_to_date_qty)}
          {unit}
        </Text>
      )}
    </View>
  );
}

function SettledBy({ documentId }: { documentId: string }) {
  const c = useColors();
  const router = useRouter();
  const settled = useQuery({
    queryKey: ["document", documentId, "allocations"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/allocations", {
          params: { path: { document_id: documentId } },
        }),
      ),
  });
  const rows = settled.data?.allocations ?? [];
  if (rows.length === 0) return null;
  return (
    <>
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Settled by
      </Text>
      <Card>
        {rows.map((a) => {
          const paymentId = a.payment_id;
          const label = paymentId ? "Payment" : "Credit note";
          return (
            <Pressable
              key={a.id}
              accessibilityRole={paymentId ? "button" : undefined}
              accessibilityLabel={`${label} ${formatInr(a.amount)} on ${formatDate(a.created_at)}`}
              disabled={!paymentId}
              onPress={() => {
                if (paymentId) router.push(`/payments/${paymentId}`);
              }}
              style={styles.amountRow}
            >
              <Text style={[styles.amountText, { color: paymentId ? c.primary : c.text }]}>
                {label} · {formatDate(a.created_at)}
              </Text>
              <Text style={[styles.amountText, { color: c.text }]}>{formatInr(a.amount)}</Text>
            </Pressable>
          );
        })}
      </Card>
    </>
  );
}

/** Why issuing did not work, and what to do about it. */
function issueError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "series_missing") {
      return `${error.message} Add a number series in the web app (Settings, Number series).`;
    }
    if (error.code === "stale_version") {
      return "Someone else changed this bill. Pull down to reload, then try again.";
    }
    if (error.problem.errors?.length) return error.problem.errors.map((e) => e.message).join(" ");
  }
  return errorMessage(error);
}

export function DocumentScreen() {
  const c = useColors();
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSession();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [issueKey, setIssueKey] = useState(newIdempotencyKey); // one per issue, renewed after
  const doc = useQuery({
    queryKey: ["document", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}", {
          params: { path: { document_id: id } },
        }),
      ),
  });
  const share = useMutation({
    mutationFn: async (d: Document) =>
      shareDocumentPdf(d.id, d.doc_number ?? documentTitle(d).replace(/\W+/g, "-")),
  });
  const issue = useMutation({
    mutationFn: async (d: Document) =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/issue", {
          params: { path: { document_id: d.id } },
          headers: { "If-Match": ifMatch(d.version), "Idempotency-Key": issueKey },
        }),
      ),
    onSuccess: (issued) => {
      setIssueKey(newIdempotencyKey());
      queryClient.setQueryData(["document", issued.id], issued);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });
  const confirmIssue = (d: Document) => {
    Alert.alert(
      `Issue this ${DOC_TYPE_LABELS[d.doc_type].toLowerCase()}?`,
      "It gets the next number and can no longer be edited.",
      [
        { text: "Not now", style: "cancel" },
        {
          text: "Issue",
          onPress: () => {
            issue.mutate(d);
          },
        },
      ],
    );
  };

  if (doc.error) {
    return (
      <View style={[styles.page, { backgroundColor: c.background }]}>
        <ErrorView error={doc.error} onRetry={() => void doc.refetch()} />
      </View>
    );
  }
  if (!doc.data) return <Loading />;
  const d = doc.data;
  const state = standing(d);
  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.page}
      refreshControl={
        <RefreshControl refreshing={doc.isRefetching} onRefresh={() => void doc.refetch()} />
      }
    >
      <Stack.Screen options={{ title: d.doc_number ?? "Draft" }} />
      <Card>
        <View style={styles.titleRow}>
          <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
            {documentTitle(d)}
          </Text>
          <Badge text={state.text} tone={state.tone} />
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Client ${d.party_name}`}
          onPress={() => {
            router.push(`/clients/${d.party_id}`);
          }}
        >
          <Text style={[styles.link, { color: c.primary }]}>{d.party_name}</Text>
        </Pressable>
        {d.project_name && <Body muted>Project: {d.project_name}</Body>}
        <Body muted>
          Dated {formatDate(d.doc_date)}
          {d.due_date ? ` · due ${formatDate(d.due_date)}` : ""}
        </Body>
        {d.reverse_charge && (
          <Body muted>Reverse charge: the client pays the GST to the government.</Body>
        )}
        {d.supply_category !== "REGULAR" && (
          <Body muted>
            {d.supply_category === "SEZ" ? "Supply to an SEZ unit" : "Export"}:{" "}
            {d.lut ? "zero-rated under the LUT, no IGST" : "zero-rated with IGST charged"}.
          </Body>
        )}
      </Card>
      {d.status !== "DRAFT" && (
        <Button
          label={share.isPending ? "Preparing the PDF…" : "Share PDF"}
          busy={share.isPending}
          onPress={() => {
            share.mutate(d);
          }}
        />
      )}
      {share.data === "preparing" && (
        <Notice tone="info" text="The PDF is still being made. Try again in a moment." />
      )}
      {share.data === "unavailable" && (
        <Notice tone="info" text="Sharing is not available on this device." />
      )}
      {share.error && <Notice text={shareErrorText(share.error)} />}
      {d.status === "DRAFT" && canIssueDocuments(session.role) && (
        <Button
          label="Issue"
          busy={issue.isPending}
          onPress={() => {
            confirmIssue(d);
          }}
        />
      )}
      {issue.error && <Notice text={issueError(issue.error)} />}
      {d.status === "ISSUED" &&
        RECEIVABLE_TYPES.includes(d.doc_type) &&
        compareMoney(d.totals.outstanding, "0") === 1 &&
        canRecordPayments(session.role) && (
          <Button
            label="Record a payment"
            variant="secondary"
            onPress={() => {
              router.push({
                pathname: "/payments/new",
                params: { party: d.party_id, document: d.id },
              });
            }}
          />
        )}
      <Totals d={d} />
      <SettledBy documentId={d.id} />
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Lines
      </Text>
      <Card style={styles.lines}>
        {d.lines.map((line) => (
          <LineRow key={line.line_no} line={line} ra={d.is_ra_bill} />
        ))}
      </Card>
      {d.notes ? <Body muted>{d.notes}</Body> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  titleRow: { flexDirection: "row", alignItems: "center", gap: space.sm, flexWrap: "wrap" },
  title: { fontSize: 18, fontWeight: "700" },
  link: { fontSize: 16, fontWeight: "600" },
  heading: { fontSize: 18, fontWeight: "700", marginTop: space.sm },
  amountRow: { flexDirection: "row", justifyContent: "space-between", gap: space.md },
  amountText: { fontSize: 15, fontVariant: ["tabular-nums"] },
  strong: { fontWeight: "700" },
  lines: { paddingVertical: 0 },
  line: { paddingVertical: space.md, gap: 2, borderBottomWidth: StyleSheet.hairlineWidth },
  lineTitle: { fontSize: 15, fontWeight: "600" },
  small: { fontSize: 13, flexShrink: 1 },
});
