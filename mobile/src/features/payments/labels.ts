import type { components } from "@/api/schema";

export const MODE_LABELS: Record<components["schemas"]["PaymentModeEnum"], string> = {
  BANK_TRANSFER: "Bank transfer",
  UPI: "UPI",
  CHEQUE: "Cheque",
  CASH: "Cash",
  CARD: "Card",
  OTHER: "Other",
};
