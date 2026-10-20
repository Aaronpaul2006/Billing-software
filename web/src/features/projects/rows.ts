/** "rows[7].rate" -> "Row 7 · rate". */
export function describeRowError(field: string | null): string {
  const m = /^rows\[(\d+)\]\.?(.*)$/.exec(field ?? "");
  if (!m) return field ?? "File";
  return `Row ${m[1] ?? ""}${m[2] ? ` · ${m[2]}` : ""}`;
}
