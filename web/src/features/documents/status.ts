import type { Status } from "@/components/status";
import { isoDate } from "@/features/dashboard/periods";
import { compareMoney } from "@/lib/money";

import { RECEIVABLE_TYPES } from "./api";
import type { DocStatus, DocType } from "./api";

interface StatusFacts {
  doc_type: DocType;
  status: DocStatus;
  due_date: string | null;
  totals: { outstanding?: string; amount_settled?: string };
}

/**
 * What a bill's badge says (D.3): its lifecycle status, and for an issued bill
 * that asks to be paid, how far it is paid: Paid (nothing outstanding), Overdue
 * (past its due date with something outstanding), Part paid, or Issued.
 * Money is compared exactly (paise from the API's strings), never as numbers.
 */
export function documentStatus(doc: StatusFacts, today: string = isoDate(new Date())): Status {
  switch (doc.status) {
    case "DRAFT":
      return "draft";
    case "CANCELLED":
      return "cancelled";
    case "ACCEPTED":
      return "accepted";
    case "DECLINED":
      return "declined";
    case "ISSUED":
      break;
  }
  const { outstanding, amount_settled: settled } = doc.totals;
  if (!RECEIVABLE_TYPES.has(doc.doc_type) || outstanding === undefined) return "issued";
  if ((compareMoney(outstanding, "0.00") ?? 1) <= 0) return "paid";
  if (doc.due_date !== null && doc.due_date < today) return "overdue";
  if (settled !== undefined && (compareMoney(settled, "0.00") ?? 0) > 0) return "part_paid";
  return "issued";
}
