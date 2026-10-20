import type { components } from "@/api/schema";

export type Category = components["schemas"]["ExpenseCategoryEnum"];

export const CATEGORY_LABELS: Record<Category, string> = {
  MATERIAL: "Material",
  LABOUR: "Labour",
  SUBCONTRACT: "Subcontract",
  EQUIPMENT: "Equipment",
  TRANSPORT: "Transport",
  SITE_OVERHEAD: "Site overhead",
  OFFICE: "Office",
  OTHER: "Other",
};
