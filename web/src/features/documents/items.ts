import type { components } from "@/api/schema";
import { sumMoney } from "@/lib/money";

export type CatalogItem = components["schemas"]["CatalogItem"];
export type BoqItem = components["schemas"]["BoqItem"];

/** What a picked item puts on the line (the server fills the same when left blank). */
export interface ItemFill {
  description: string;
  unit: string | null;
  sac_hsn: string | null;
  rate: string | null;
  gst_rate: string;
}

/** `key` is the line's item: "boq:<id>", "cat:<id>" or "var:<item id>:<variant id>". */
export interface PickedItem {
  key: string;
  label: string;
  fill: ItemFill;
}

export function catalogChoices(items: CatalogItem[]): PickedItem[] {
  return items.flatMap((c) => [
    {
      key: `cat:${c.id}`,
      label: c.name,
      fill: {
        description: c.description ?? c.name,
        unit: c.unit,
        sac_hsn: c.sac_hsn,
        rate: c.default_rate,
        gst_rate: c.gst_rate,
      },
    },
    ...c.variants
      .filter((v) => v.is_active)
      .map((v) => ({
        key: `var:${c.id}:${v.id}`,
        label: `${c.name} — ${v.attribute}: ${v.value}`,
        fill: {
          description: `${c.description ?? c.name} — ${v.attribute}: ${v.value}`,
          unit: c.unit,
          sac_hsn: c.sac_hsn,
          // the item's rate plus the variant's change, added exactly (paise), as the server does
          rate: c.default_rate ? sumMoney([c.default_rate, v.rate_delta]) : null,
          gst_rate: c.gst_rate,
        },
      })),
  ]);
}

export function boqChoices(items: BoqItem[]): PickedItem[] {
  return items.map((b) => ({
    key: `boq:${b.id}`,
    label: `${b.item_code} · ${b.description}`,
    fill: {
      description: b.description,
      unit: b.unit,
      sac_hsn: b.sac_hsn,
      rate: b.rate,
      gst_rate: b.gst_rate,
    },
  }));
}

/** Roles that may add items and clients (masters.edit, docs/01-architecture.md §3). */
export const MAY_ADD_MASTERS: ReadonlySet<string> = new Set(["OWNER", "ADMIN", "ACCOUNTANT"]);
