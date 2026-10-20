import type { components } from "@/api/schema";

type Mode = components["schemas"]["PaymentModeEnum"];

export const MODE_LABELS: Record<Mode, string> = {
  BANK_TRANSFER: "Bank transfer",
  UPI: "UPI",
  CHEQUE: "Cheque",
  CASH: "Cash",
  CARD: "Card",
  OTHER: "Other",
};
