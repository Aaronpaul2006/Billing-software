/**
 * Reporting periods in the Indian financial year (1 April - 31 March).
 * Dates are local calendar dates as "YYYY-MM-DD"; the server works out the
 * previous period for comparison.
 */

export type PeriodKey = "this_month" | "last_month" | "this_fy" | "last_fy";

export const PERIOD_LABELS: Record<PeriodKey, string> = {
  this_month: "This month",
  last_month: "Last month",
  this_fy: "This financial year",
  last_fy: "Last financial year",
};

export function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The year the financial year containing `d` starts in (April 2026 - March 2027 -> 2026). */
export function fyStartYear(d: Date): number {
  return d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
}

export function periodRange(key: PeriodKey, today: Date): { from: string; to: string } {
  const y = today.getFullYear();
  const m = today.getMonth();
  switch (key) {
    case "this_month":
      return { from: isoDate(new Date(y, m, 1)), to: isoDate(today) };
    case "last_month":
      return { from: isoDate(new Date(y, m - 1, 1)), to: isoDate(new Date(y, m, 0)) };
    case "this_fy": {
      const fy = fyStartYear(today);
      return { from: `${fy}-04-01`, to: isoDate(today) };
    }
    case "last_fy": {
      const fy = fyStartYear(today) - 1;
      return { from: `${fy}-04-01`, to: `${fy + 1}-03-31` };
    }
  }
}

/** "2026-10-01".."2026-10-20" -> "1 Oct – 20 Oct 2026". */
export function formatRange(from: string, to: string): string {
  const parse = (s: string) => {
    const [y = 0, mo = 1, d = 1] = s.split("-").map(Number);
    return new Date(y, mo - 1, d);
  };
  const a = parse(from);
  const b = parse(to);
  const day = (d: Date) => d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return `${day(a)}${a.getFullYear() !== b.getFullYear() ? ` ${a.getFullYear()}` : ""} – ${day(b)} ${b.getFullYear()}`;
}
