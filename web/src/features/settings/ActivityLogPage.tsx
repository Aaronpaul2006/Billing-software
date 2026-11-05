import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { LoadMore } from "@/components/LoadMore";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatDateTime } from "@/lib/dates";

type Entry = components["schemas"]["AuditEntry"];
type RecordType = components["schemas"]["RecordTypeEnum"];

/** The kinds of record to filter by, as people call them. */
const KINDS: { value: RecordType; label: string }[] = [
  { value: "documents", label: "Bills and quotations" },
  { value: "payments", label: "Payments" },
  { value: "expenses", label: "Expenses" },
  { value: "parties", label: "Clients and vendors" },
  { value: "projects", label: "Projects" },
  { value: "boq_items", label: "BOQ items" },
  { value: "catalog_items", label: "Catalog" },
  { value: "retention_releases", label: "Retention releases" },
  { value: "tds_certificates", label: "TDS certificates" },
  { value: "memberships", label: "Members" },
  { value: "tenants", label: "Company details" },
  { value: "gst_registrations", label: "GST registrations" },
  { value: "document_series", label: "Number series" },
  { value: "print_settings", label: "Bill printing" },
];

/** Where a record can be opened, when it has a page of its own. */
function recordLink(e: Entry): string | null {
  if (e.action === "deleted") return null;
  switch (e.record_type) {
    case "documents":
      return `/documents/${e.record_id}`;
    case "payments":
      return `/payments/${e.record_id}`;
    case "expenses":
      return `/expenses/${e.record_id}`;
    case "parties":
      return `/parties/${e.record_id}`;
    case "projects":
      return `/projects/${e.record_id}`;
    default:
      return null;
  }
}

function what(e: Entry): string {
  const fields = e.changed_fields.length ? `: ${e.changed_fields.join(", ")}` : "";
  return `${e.action.charAt(0).toUpperCase()}${e.action.slice(1)}${fields}`;
}

const columns: Column<Entry>[] = [
  {
    id: "record",
    header: "Record",
    card: "title",
    className: "whitespace-normal",
    cell: (e) => {
      const to = recordLink(e);
      const name = e.record || e.record_type_label;
      return (
        <>
          {to ? (
            <Link to={to} className="font-medium hover:underline">
              {name}
            </Link>
          ) : (
            <span className="font-medium">{name}</span>
          )}
          {e.record && <div className="text-help text-muted-foreground">{e.record_type_label}</div>}
        </>
      );
    },
  },
  { id: "what", header: "What", className: "whitespace-normal", cell: what },
  { id: "who", header: "Who", card: "subtitle", cell: (e) => e.actor_name ?? "The system" },
  {
    id: "when",
    header: "When",
    card: "badge",
    cell: (e) => (
      <span className="text-help text-muted-foreground">{formatDateTime(e.occurred_at)}</span>
    ),
  },
];

/**
 * The activity log (Part B): who changed what, and when, across the business.
 * Owners and admins only; field names are shown, never their values.
 */
export function ActivityLogPage() {
  const [actor, setActor] = useState("");
  const [kind, setKind] = useState<RecordType | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const members = useQuery({
    queryKey: ["members"],
    queryFn: async () => unwrap(await api.GET("/api/v1/members")).results,
  });
  const log = useInfiniteQuery({
    queryKey: ["audit-log", { actor, kind, from, to }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/audit-log", {
          params: {
            query: {
              ...(actor ? { actor_id: actor } : {}),
              ...(kind ? { record_type: kind } : {}),
              ...(from ? { date_from: from } : {}),
              ...(to ? { date_to: to } : {}),
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = log.data?.pages.flatMap((p) => p.results) ?? [];
  const filtered = actor !== "" || kind !== "" || from !== "" || to !== "";

  return (
    <>
      <PageHeader
        title="Activity log"
        description="Who changed what, and when. Every change is recorded and cannot be edited."
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field id="log-who" label="Who">
          <NativeSelect
            id="log-who"
            value={actor}
            onChange={(e) => {
              setActor(e.target.value);
            }}
          >
            <option value="">Everyone</option>
            {(members.data ?? []).map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field id="log-kind" label="What">
          <NativeSelect
            id="log-kind"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as RecordType | "");
            }}
          >
            <option value="">Everything</option>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field id="log-from" label="From">
          <Input
            id="log-from"
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
            }}
          />
        </Field>
        <Field id="log-to" label="To">
          <Input
            id="log-to"
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
            }}
          />
        </Field>
      </div>
      {log.error ? (
        <ErrorState error={log.error} />
      ) : (
        <>
          <DataTable
            label="Activity log"
            rows={rows}
            columns={columns}
            rowKey={(e) => String(e.id)}
            rowLabel={(e) => `${e.record_type_label} ${e.record}`}
            loading={log.isPending}
            empty={
              filtered
                ? {
                    title: "Nothing matches these filters",
                    action: (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setActor("");
                          setKind("");
                          setFrom("");
                          setTo("");
                        }}
                      >
                        Clear the filters
                      </Button>
                    ),
                  }
                : { title: "Nothing recorded yet" }
            }
          />
          <LoadMore query={log} />
        </>
      )}
    </>
  );
}
