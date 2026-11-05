import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { Money } from "@/components/Money";
import { SavedFilters } from "@/components/SavedFilters";
import { toPaise } from "@/lib/money";

interface Row {
  id: string;
  name: string;
  amount: string;
}

const ROWS: Row[] = [
  { id: "a", name: "Brickwork", amount: "1000.00" },
  { id: "b", name: "Excavation", amount: "250000.00" },
  { id: "c", name: "Plastering", amount: "99.50" },
];

const COLUMNS: Column<Row>[] = [
  {
    id: "name",
    header: "Item",
    card: "title",
    sortable: true,
    sortValue: (r) => r.name,
    cell: (r) => r.name,
  },
  {
    id: "amount",
    header: "Amount",
    align: "right",
    card: "amount",
    sortable: true,
    sortValue: (r) => toPaise(r.amount),
    cell: (r) => <Money value={r.amount} />,
  },
];

function narrow(matches: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches,
    media: q,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const bodyRows = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.textContent);

describe("DataTable (D.4)", () => {
  it("sorts amounts exactly (by paise), both ways, and says so to screen readers", async () => {
    const user = userEvent.setup();
    render(<DataTable label="Items" rows={ROWS} columns={COLUMNS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("table", { name: "Items" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Amount" }));
    expect(bodyRows()).toEqual([
      "Plastering₹99.50",
      "Brickwork₹1,000.00",
      "Excavation₹2,50,000.00",
    ]);
    expect(screen.getByRole("columnheader", { name: "Amount" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    await user.click(screen.getByRole("button", { name: "Amount" }));
    expect(bodyRows()[0]).toBe("Excavation₹2,50,000.00");
    expect(screen.getByRole("columnheader", { name: "Amount" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("hands sorting to the server when asked", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <DataTable
        label="Items"
        rows={ROWS}
        columns={COLUMNS}
        rowKey={(r) => r.id}
        sort={{ column: "name", direction: "asc" }}
        onSortChange={onSortChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Item" }));
    expect(onSortChange).toHaveBeenCalledWith({ column: "name", direction: "desc" });
    expect(bodyRows()[0]).toBe("Brickwork₹1,000.00"); // the server's order is kept as given
  });

  it("row actions, totals and the compact choice", async () => {
    const user = userEvent.setup();
    const remove = vi.fn();
    render(
      <DataTable
        label="Items"
        rows={ROWS}
        columns={COLUMNS}
        rowKey={(r) => r.id}
        rowLabel={(r) => r.name}
        rowActions={(r) => [
          {
            label: "Delete",
            tone: "danger",
            onSelect: () => {
              remove(r.id);
            },
          },
        ]}
        totals={{ label: "Total", cells: { amount: <Money value="251099.50" /> } }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "More actions for Excavation" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(remove).toHaveBeenCalledWith("b");
    expect(screen.getAllByRole("row").at(-1)).toHaveTextContent("Total₹2,51,099.50");
    const compact = screen.getByRole("button", { name: "Compact rows" });
    await user.click(compact);
    expect(compact).toHaveAttribute("aria-pressed", "true");
    expect(window.localStorage.getItem("app.tableDensity")).toBe("compact");
  });

  it("an empty list says what to do; loading is announced", () => {
    const { rerender } = render(
      <DataTable
        label="Items"
        rows={[]}
        columns={COLUMNS}
        rowKey={(r) => r.id}
        empty={{ title: "No items yet", action: <button type="button">Add an item</button> }}
      />,
    );
    expect(screen.getByText("No items yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add an item" })).toBeInTheDocument();
    rerender(<DataTable label="Items" rows={[]} columns={COLUMNS} rowKey={(r) => r.id} loading />);
    expect(screen.getByRole("table", { name: "Items" })).toHaveAttribute("aria-busy", "true");
  });

  it("becomes cards on narrow screens, with every amount visible", () => {
    narrow(false);
    render(<DataTable label="Items" rows={ROWS} columns={COLUMNS} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("table")).toBeNull();
    const cards = within(screen.getByRole("list", { name: "Items" })).getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    const second = cards[1] as HTMLElement;
    expect(second).toHaveTextContent("Excavation");
    expect(within(second).getByText("Amount")).toBeInTheDocument();
    expect(second).toHaveTextContent("₹2,50,000.00");
  });
});

describe("saved filters (D.4)", () => {
  it("saves the filters in use under a name and applies them later", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(
      <SavedFilters list="bills" current={{ status: "ISSUED", search: "INV" }} onApply={onApply} />,
    );
    await user.click(screen.getByRole("button", { name: "Saved filters" }));
    await user.click(await screen.findByRole("menuitem", { name: "Save or remove…" }));
    await user.type(await screen.findByLabelText("Name"), "Issued bills");
    await user.click(screen.getByRole("button", { name: "Save these filters" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await user.click(screen.getByRole("button", { name: "Saved filters" }));
    await user.click(await screen.findByRole("menuitem", { name: "Issued bills" }));
    expect(onApply).toHaveBeenCalledWith({ status: "ISSUED", search: "INV" });
    expect(JSON.parse(window.localStorage.getItem("app.savedFilters.bills") ?? "[]")).toHaveLength(
      1,
    );
  });
});
