/**
 * Every status in the app, with one colour meaning each (D.3): grey for
 * not yet sent, blue for sent and open, amber for part paid, green for done
 * well, red for late, muted for no longer counting.
 */
export type Status =
  | "draft"
  | "issued"
  | "part_paid"
  | "paid"
  | "overdue"
  | "accepted"
  | "declined"
  | "cancelled"
  | "voided"
  | "planned"
  | "active"
  | "on_hold"
  | "completed";

export const STATUS_TEXT: Record<Status, string> = {
  draft: "Draft",
  issued: "Issued",
  part_paid: "Part paid",
  paid: "Paid",
  overdue: "Overdue",
  accepted: "Accepted",
  declined: "Declined",
  cancelled: "Cancelled",
  voided: "Voided",
  planned: "Planned",
  active: "Active",
  on_hold: "On hold",
  completed: "Completed",
};
