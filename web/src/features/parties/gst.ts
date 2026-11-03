import type { components } from "@/api/schema";

export type Treatment = components["schemas"]["PartyWrite"]["gst_treatment"];

/** How a client is registered under GST, in plain words (client page and the bill screen's popup). */
export const TREATMENTS: { value: Treatment; label: string }[] = [
  { value: "REGISTERED", label: "Registered business (has GSTIN)" },
  { value: "COMPOSITION", label: "Composition dealer (has GSTIN)" },
  { value: "SEZ", label: "SEZ unit (has GSTIN)" },
  { value: "UNREGISTERED", label: "Unregistered business" },
  { value: "CONSUMER", label: "Consumer (individual)" },
  { value: "OVERSEAS", label: "Overseas" },
];
export const NEEDS_GSTIN: ReadonlySet<Treatment> = new Set(["REGISTERED", "COMPOSITION", "SEZ"]);
