/**
 * A downloaded file (a PDF from the API). Not `instanceof Blob` alone: a Blob
 * made by another realm (the test environment's fetch on Node 22) fails that
 * check although it is a real file.
 */
export function isBlob(value: unknown): value is Blob {
  return (
    value instanceof Blob ||
    (typeof value === "object" &&
      value !== null &&
      typeof (value as Partial<Blob>).arrayBuffer === "function" &&
      typeof (value as Partial<Blob>).size === "number")
  );
}
