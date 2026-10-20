import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import { compareMoney, formatInr, subtractMoney, sumMoney, toPaise } from "@/lib/money";

type AllocationIn = components["schemas"]["AllocationIn"];

/** Something the party owes that money can settle. Keys: "doc:<id>" / "rel:<id>". */
export interface OpenItem {
  key: string;
  label: string;
  detail: string;
  date: string;
  outstanding: string;
  href?: string;
}

/** Allocation amounts per open item, as typed. */
export type Allocations = Record<string, string>;

export function useOpenItems(partyId: string, includeReleases: boolean) {
  return useQuery({
    queryKey: ["open-items", partyId, includeReleases],
    enabled: partyId !== "",
    queryFn: async (): Promise<OpenItem[]> => {
      const documents = unwrap(
        await api.GET("/api/v1/documents", {
          params: {
            query: {
              party_id: partyId,
              status: ["ISSUED"],
              payment_state: "OPEN",
              doc_type: ["TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE"],
              ordering: "doc_date,doc_number", // oldest first; same day: by number
              limit: 100,
            },
          },
        }),
      ).results;
      const items: OpenItem[] = documents.map((d) => ({
        key: `doc:${d.id}`,
        label: d.doc_number ?? "",
        detail: DOC_TYPE_LABELS[d.doc_type],
        date: d.doc_date,
        outstanding: d.totals.outstanding,
        href: `/documents/${d.id}`,
      }));
      if (includeReleases) {
        const releases = unwrap(
          await api.GET("/api/v1/retention-releases", {
            params: {
              query: {
                party_id: partyId,
                status: "RELEASED",
                ordering: "release_date",
                limit: 100,
              },
            },
          }),
        ).results;
        for (const r of releases) {
          if (compareMoney(r.outstanding, "0") !== 1) continue;
          items.push({
            key: `rel:${r.id}`,
            label: r.reference ?? "Retention release",
            detail: "Retention release",
            date: r.release_date,
            outstanding: r.outstanding,
          });
        }
        items.sort((a, b) => a.date.localeCompare(b.date));
      }
      return items;
    },
  });
}

/** The allocations to send: only amounts above zero. */
export function toAllocationItems(allocations: Allocations): AllocationIn[] {
  return Object.entries(allocations)
    .filter(([, amount]) => (toPaise(amount) ?? 0n) > 0n)
    .map(([key, amount]) => {
      const [kind, id = ""] = key.split(":");
      const cleaned = subtractMoney(amount, "0") ?? amount; // normalised "1234.50"
      return kind === "rel"
        ? { retention_release_id: id, amount: cleaned }
        : { document_id: id, amount: cleaned };
    });
}

/** Problems the server would refuse anyway, found while typing. */
export function allocationProblems(
  items: readonly OpenItem[],
  allocations: Allocations,
  available: string,
): string[] {
  const problems: string[] = [];
  for (const item of items) {
    const amount = allocations[item.key] ?? "";
    if (amount.trim() === "") continue;
    if (toPaise(amount) === null) problems.push(`${item.label}: not an amount.`);
    else if (compareMoney(amount, item.outstanding) === 1)
      problems.push(`${item.label}: more than the ${formatInr(item.outstanding)} outstanding.`);
  }
  const total = sumMoney(Object.values(allocations));
  if (total !== null && compareMoney(total, available) === 1)
    problems.push(`More than the ${formatInr(available)} available.`);
  return problems;
}
