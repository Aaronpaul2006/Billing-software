import type { Status } from "@/components/status";
import { isoDate } from "@/features/dashboard/periods";
import { compareMoney } from "@/lib/money";

import type { VendorBill } from "./api";

/** A vendor bill's state, as the badges say it (paid / part paid / overdue). */
export function billStatus(b: VendorBill, today = isoDate(new Date())): Status | null {
  if (b.status === "VOIDED") return "voided";
  if (compareMoney(b.outstanding, "0") !== 1) return "paid";
  const due = b.due_date ?? b.bill_date;
  if (due < today) return "overdue";
  return compareMoney(b.amount_paid, "0") === 1 ? "part_paid" : null;
}
