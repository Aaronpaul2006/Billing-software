/**
 * One way to write dates everywhere (design step D.1):
 *   formatDate("2026-10-25")                -> "25 Oct 2026"
 *   formatDateTime("2026-11-04T08:21:32Z")  -> "4 Nov 2026, 1:51 pm"  (the browser's time zone)
 *   formatDayMonth("2026-10-25")            -> "25 Oct"
 *   formatMonthYear("2026-10-01")           -> "Oct 2026"
 *   formatTime(new Date())                  -> "8:21 am"
 * Plain dates ("YYYY-MM-DD") are calendar days: they are never shifted by the
 * time zone. Empty values show as an en dash (or the given fallback).
 */

const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const DAY_MONTH = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const MONTH_YEAR = new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });

const PLAIN_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A calendar day from "YYYY-MM-DD" (local, no time zone shift) or a moment from a timestamp. */
function toDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  const plain = PLAIN_DATE.exec(value);
  if (plain) return new Date(Number(plain[1]), Number(plain[2]) - 1, Number(plain[3]));
  return new Date(value);
}

type DateInput = string | Date | null | undefined;

export function formatDate(value: DateInput, fallback = "–"): string {
  return value ? DAY.format(toDate(value)) : fallback;
}

export function formatDayMonth(value: DateInput, fallback = "–"): string {
  return value ? DAY_MONTH.format(toDate(value)) : fallback;
}

export function formatMonthYear(value: DateInput, fallback = "–"): string {
  return value ? MONTH_YEAR.format(toDate(value)) : fallback;
}

export function formatTime(value: DateInput, fallback = "–"): string {
  return value ? TIME.format(toDate(value)) : fallback;
}

export function formatDateTime(value: DateInput, fallback = "–"): string {
  if (!value) return fallback;
  const d = toDate(value);
  return `${DAY.format(d)}, ${TIME.format(d)}`;
}
