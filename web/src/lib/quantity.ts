/**
 * Measurement-sheet arithmetic (B.9), exact: quantities have at most 3 decimals,
 * so they are worked out as whole thousandths (BigInt), never as floats. The
 * server does the same sums; this only shows the total while typing.
 */

const QTY = /^\d{1,11}(\.\d{1,3})?$/;
const SCALE = 1000n;

/** "10.5" -> 10500n (thousandths); null when not a plain quantity. */
function milli(text: string): bigint | null {
  const t = text.trim().replace(/,/g, "");
  if (!QTY.test(t)) return null;
  const [whole = "0", frac = ""] = t.split(".");
  return BigInt(whole) * SCALE + BigInt(frac.padEnd(3, "0"));
}

function fromMilli(value: bigint): string {
  const sign = value < 0n ? "-" : "";
  const abs = value < 0n ? -value : value;
  const frac = (abs % SCALE).toString().padStart(3, "0");
  return `${sign}${(abs / SCALE).toString()}.${frac}`;
}

export interface MeasureRow {
  nos: string;
  length: string;
  breadth: string;
  height: string;
  deduct: boolean;
}

/** One row: nos x L x B x H (empty sizes count as 1), half up to 3 decimals; null if invalid. */
export function rowQuantity(row: MeasureRow): string | null {
  const factors = [row.nos, row.length, row.breadth, row.height].filter((v) => v.trim() !== "");
  if (factors.length === 0) return fromMilli(SCALE); // 1 x 1 x 1 x 1
  // The exact product, in units of 1000^-k, then rounded half up once (as the server does).
  let product = 1n;
  let divisor = 1n;
  for (const f of factors) {
    const v = milli(f);
    if (v === null || v === 0n) return null;
    product *= v;
    divisor *= SCALE;
  }
  divisor /= SCALE; // the result is in thousandths
  const rounded = (product + divisor / 2n) / divisor;
  return rounded > 0n ? fromMilli(rounded) : null;
}

/** The line's quantity: the rows' total (deduct rows taken off); null when a row is invalid. */
export function measuredTotal(rows: MeasureRow[]): string | null {
  let total = 0n;
  for (const row of rows) {
    const q = rowQuantity(row);
    if (q === null) return null;
    const v = milli(q) ?? 0n;
    total += row.deduct ? -v : v;
  }
  return fromMilli(total);
}
