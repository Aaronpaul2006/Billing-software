import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { ConfirmProvider } from "@/components/ConfirmDialog";
import { useConfirm } from "@/components/confirm-context";
import { Money, MoneyCell } from "@/components/Money";
import { StatusBadge } from "@/components/StatusBadge";
import { ToastProvider } from "@/components/Toast";
import { useToast } from "@/components/toast-context";
import { Table, TableBody, TableRow } from "@/components/ui/table";
import { documentStatus } from "@/features/documents/status";

function Asker() {
  const confirm = useConfirm();
  const [answer, setAnswer] = useState("none");
  return (
    <>
      <button
        type="button"
        onClick={() => {
          void confirm({
            title: "Delete this draft?",
            description: "The draft is removed for good.",
            confirmLabel: "Delete draft",
            tone: "danger",
          }).then((yes) => {
            setAnswer(String(yes));
          });
        }}
      >
        Ask
      </button>
      <p>answer: {answer}</p>
    </>
  );
}

describe("confirm dialog (D.3)", () => {
  it("asks with a title, an explanation and named buttons", async () => {
    const user = userEvent.setup();
    render(
      <ConfirmProvider>
        <Asker />
      </ConfirmProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Ask" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete this draft?" });
    expect(dialog).toHaveAccessibleDescription("The draft is removed for good.");
    await user.click(within(dialog).getByRole("button", { name: "Delete draft" }));
    expect(await screen.findByText("answer: true")).toBeInTheDocument();
  });

  it("Esc answers no", async () => {
    const user = userEvent.setup();
    render(
      <ConfirmProvider>
        <Asker />
      </ConfirmProvider>,
    );
    const ask = screen.getByRole("button", { name: "Ask" });
    await user.click(ask);
    await screen.findByRole("alertdialog");
    // a direct key event: user-event's simulated keyboard stalls on this dialog in jsdom
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(await screen.findByText("answer: false")).toBeInTheDocument();
    // focus going back to "Ask" is checked in a real browser (tools/design-audit);
    // jsdom does not run Radix's deferred focus return reliably
  });
});

function Notifier({ duration }: { duration?: number }) {
  const toast = useToast();
  const [undone, setUndone] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          toast({
            message: "Line 3 removed.",
            duration,
            action: {
              label: "Undo",
              onClick: () => {
                setUndone(true);
              },
            },
          });
        }}
      >
        Remove
      </button>
      {undone && <p>Line 3 is back</p>}
    </>
  );
}

describe("toasts (D.3)", () => {
  it("shows a message with Undo, in a live region", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Notifier />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByLabelText("Notifications")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Line 3 removed.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByText("Line 3 is back")).toBeInTheDocument();
    expect(screen.queryByText("Line 3 removed.")).toBeNull();
  });

  it("goes away by itself", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Notifier duration={50} />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(screen.queryByText("Line 3 removed.")).toBeNull();
    });
  });
});

describe("status badges and amounts (D.3)", () => {
  const bill = (over: Partial<Parameters<typeof documentStatus>[0]> = {}) => ({
    doc_type: "TAX_INVOICE" as const,
    status: "ISSUED" as const,
    due_date: "2026-11-30",
    totals: { outstanding: "1000.00", amount_settled: "0.00" },
    ...over,
  });

  it("works out a bill's payment state from exact amounts", () => {
    const today = "2026-11-05";
    expect(documentStatus(bill(), today)).toBe("issued");
    expect(
      documentStatus(bill({ totals: { outstanding: "500.00", amount_settled: "500.00" } }), today),
    ).toBe("part_paid");
    expect(
      documentStatus(bill({ totals: { outstanding: "0.00", amount_settled: "1000.00" } }), today),
    ).toBe("paid");
    expect(documentStatus(bill({ due_date: "2026-11-01" }), today)).toBe("overdue");
    expect(documentStatus(bill({ status: "DRAFT" }), today)).toBe("draft");
    expect(documentStatus(bill({ status: "CANCELLED" }), today)).toBe("cancelled");
    expect(documentStatus(bill({ doc_type: "QUOTATION", status: "ACCEPTED" }), today)).toBe(
      "accepted",
    );
    expect(documentStatus(bill({ doc_type: "CREDIT_NOTE" }), today)).toBe("issued");
  });

  it("shows each status in words", () => {
    render(<StatusBadge status="part_paid" />);
    expect(screen.getByText("Part paid")).toHaveAttribute("data-status", "part_paid");
  });

  it("formats amounts from strings and right-aligns them in tables", () => {
    render(
      <>
        <Money value="341020.5" />
        <Money value={null} />
        <Table>
          <TableBody>
            <TableRow>
              <MoneyCell value="1500000.00" />
            </TableRow>
          </TableBody>
        </Table>
      </>,
    );
    expect(screen.getByText("₹3,41,020.50")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
    expect(screen.getByText("₹15,00,000.00").closest("td")).toHaveClass("text-right");
  });
});
