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
