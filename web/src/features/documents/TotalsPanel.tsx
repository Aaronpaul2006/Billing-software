import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

import type { Totals } from "./api";

const ZERO = /^-?0+(\.0+)?$/;

function Row({
  label,
  value,
  strong,
  minus,
}: {
  label: string;
  value: string | undefined;
  strong?: boolean;
  minus?: boolean;
}) {
  if (value === undefined) return null;
  return (
    <div
      className={cn("flex justify-between gap-6 py-0.5", strong && "border-t pt-2 font-semibold")}
    >
      <dt>{label}</dt>
      <dd className="tabular-nums">
        {minus ? "− " : ""}
        {formatInr(value)}
      </dd>
    </div>
  );
}

/**
 * Totals exactly as the server computed them (never added up here):
 * tax by CGST + SGST or IGST, round-off, deductions, what the client pays now.
 */
export function TotalsPanel({
  totals,
  intraState,
  showSettlement = false,
  reverseCharge = false,
}: {
  totals: Totals;
  intraState: boolean;
  showSettlement?: boolean;
  /** Tax shown for the record; the client pays it, so it is not in the total. */
  reverseCharge?: boolean;
}) {
  const tax = (name: string) => (reverseCharge ? `${name} (paid by the client)` : name);
  const nonZero = (v: string | undefined) => (v !== undefined && !ZERO.test(v) ? v : undefined);
  const deductions = [
    ["Retention", totals.retention],
    ["Income-tax TDS", totals.income_tax_tds],
    ["GST TDS", totals.gst_tds],
    ["Advance recovered", totals.advance_recovery],
  ].filter(([, v]) => nonZero(v)) as [string, string][];
  return (
    <dl className="grid min-w-72 text-sm" aria-label="Totals">
      <Row label="Taxable value" value={totals.subtotal} />
      {intraState ? (
        <>
          <Row label={tax("CGST")} value={totals.cgst} />
          <Row label={tax("SGST")} value={totals.sgst} />
        </>
      ) : (
        <Row label={tax("IGST")} value={totals.igst} />
      )}
      <Row label="Cess" value={nonZero(totals.cess)} />
      <Row label="Round off" value={nonZero(totals.round_off)} />
      <Row label="Total" value={totals.grand_total} strong />
      {deductions.map(([label, value]) => (
        <Row key={label} label={`Less ${label.toLowerCase()}`} value={value} minus />
      ))}
      {deductions.length > 0 && <Row label="Receivable now" value={totals.net_receivable} strong />}
      {showSettlement && (
        <>
          <Row label="Received" value={totals.amount_settled} />
          <Row label="Outstanding" value={totals.outstanding} strong />
        </>
      )}
    </dl>
  );
}
