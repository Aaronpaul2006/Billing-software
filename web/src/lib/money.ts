/**
 * Money is a string end to end ("341020.00"), exactly as the API sends it.
 * It is never turned into a JavaScript number: floats cannot hold paise
 * exactly, and the server does all arithmetic (Decimal, ROUND_HALF_UP).
 * These helpers only format and validate.
 */

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Indian digit grouping of a digit string: "34102000" -> "3,41,02,000". */
export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  return `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`;
}

/**
 * "341020.00" -> "₹3,41,020.00"; "-8024.00" -> "-₹8,024.00".
 * Never rounds: an amount with more than two decimals is shown in full.
 * Anything that is not a plain decimal string is returned unchanged.
 */
export function formatInr(
  amount: string | null | undefined,
  { symbol = true }: { symbol?: boolean } = {},
): string {
  if (amount == null || amount === "") return "";
  const match = DECIMAL.exec(amount.trim());
  if (!match) return amount;
  const [, sign = "", integer = "0", fraction = ""] = match;
  const decimals = fraction.length >= 2 ? fraction : fraction.padEnd(2, "0");
  const grouped = groupIndian(integer.replace(/^0+(?=\d)/, ""));
  return `${sign}${symbol ? "₹" : ""}${grouped}.${decimals}`;
}

/** A quantity as the API sends it ("42.500") without trailing zeros: "42.5". */
export function formatQty(quantity: string | null | undefined): string {
  if (quantity == null || quantity === "") return "";
  const match = DECIMAL.exec(quantity.trim());
  if (!match) return quantity;
  const [, sign = "", integer = "0", fraction = ""] = match;
  const trimmed = fraction.replace(/0+$/, "");
  return `${sign}${groupIndian(integer)}${trimmed ? `.${trimmed}` : ""}`;
}

/** What a money input may contain before it is sent: up to 2 decimals, no sign. */
export const MONEY_INPUT = /^\d{1,12}(\.\d{1,2})?$/;

/** Normalise user input for the API: strips ₹, spaces and grouping commas. */
export function cleanMoneyInput(raw: string): string {
  return raw.replace(/[₹,\s]/g, "");
}

/*
 * Exact arithmetic for the few sums the screen must show before the server
 * answers (what is left to allocate). Amounts become whole paise as BigInt:
 * no floats anywhere. The server still checks everything.
 */

const MONEY_STRICT = /^(-)?(\d+)(?:\.(\d{1,2}))?$/;

/** "1234.5" -> 123450n paise; null for anything that is not an amount. */
export function toPaise(amount: string): bigint | null {
  const m = MONEY_STRICT.exec(cleanMoneyInput(amount));
  if (!m) return null;
  const [, sign, rupees = "0", paise = ""] = m;
  const value = BigInt(rupees) * 100n + BigInt(paise.padEnd(2, "0"));
  return sign ? -value : value;
}

/** 123450n -> "1234.50". */
export function fromPaise(paise: bigint): string {
  const sign = paise < 0n ? "-" : "";
  const abs = paise < 0n ? -paise : paise;
  return `${sign}${String(abs / 100n)}.${String(abs % 100n).padStart(2, "0")}`;
}

/** The sum of amounts; blanks count as zero, anything unreadable makes it null. */
export function sumMoney(amounts: readonly string[]): string | null {
  let total = 0n;
  for (const a of amounts) {
    if (a.trim() === "") continue;
    const p = toPaise(a);
    if (p === null) return null;
    total += p;
  }
  return fromPaise(total);
}

/** a - b, or null if either is not an amount. */
export function subtractMoney(a: string, b: string): string | null {
  const x = toPaise(a);
  const y = toPaise(b);
  return x === null || y === null ? null : fromPaise(x - y);
}

/** Compare two amounts: -1, 0, 1 (null if either is not an amount). */
export function compareMoney(a: string, b: string): -1 | 0 | 1 | null {
  const x = toPaise(a);
  const y = toPaise(b);
  if (x === null || y === null) return null;
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * Spread `available` over `owed` in order (oldest first): each gets
 * min(owed, what is left). Returns the amounts as strings ("" for none).
 */
export function fillInOrder(available: string, owed: readonly string[]): string[] {
  let left = toPaise(available) ?? 0n;
  return owed.map((o) => {
    const due = toPaise(o) ?? 0n;
    const take = left <= 0n ? 0n : due < left ? due : left;
    left -= take;
    return take > 0n ? fromPaise(take) : "";
  });
}
