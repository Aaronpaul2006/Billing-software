import { fromPaise, percentOf, qtyTimesRate, sumMoney, toMilli, toPaise } from "@/lib/money";

import type { WorkOrderDetail } from "./api";

/** What the server will work out, shown before saving (the server decides). */
export function raTotals(order: WorkOrderDetail, qty: Record<string, string>) {
  const lines = order.items
    .filter((i) => (toMilli(qty[i.id] ?? "") ?? 0n) > 0n)
    .map((i) => {
      const amount = qtyTimesRate(qty[i.id] ?? "", i.rate) ?? "0.00";
      return { amount, gst: percentOf(amount, i.gst_rate) ?? "0.00" };
    });
  const taxable = sumMoney(lines.map((l) => l.amount)) ?? "0.00";
  const gst = sumMoney(lines.map((l) => l.gst)) ?? "0.00";
  const tds = order.tds_section ? (percentOf(taxable, order.tds_rate, true) ?? "0.00") : "0.00";
  const retention = percentOf(taxable, order.retention_pct) ?? "0.00";
  const net =
    (toPaise(taxable) ?? 0n) +
    (toPaise(gst) ?? 0n) -
    (toPaise(tds) ?? 0n) -
    (toPaise(retention) ?? 0n);
  return { count: lines.length, taxable, gst, tds, retention, net: fromPaise(net) };
}
