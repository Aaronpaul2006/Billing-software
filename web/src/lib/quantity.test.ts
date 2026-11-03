import { measuredTotal, rowQuantity } from "./quantity";

const row = (nos: string, length = "", breadth = "", height = "", deduct = false) => ({
  nos,
  length,
  breadth,
  height,
  deduct,
});

describe("measurement arithmetic", () => {
  it("multiplies exactly and rounds half up once, like the server", () => {
    expect(rowQuantity(row("2", "10.5", "3.2"))).toBe("67.200");
    expect(rowQuantity(row("", "2.125", "1.333"))).toBe("2.833"); // 2.832625
    expect(rowQuantity(row("3", "0.333", "0.5"))).toBe("0.500"); // 0.4995 -> 0.500
    expect(rowQuantity(row("", "", "", ""))).toBe("1.000");
  });

  it("totals rows, taking deductions off", () => {
    expect(measuredTotal([row("2", "10.5", "3.2"), row("", "2.5", "3", "", true)])).toBe("59.700");
    expect(measuredTotal([row("1", "2"), row("1", "2", "", "", true)])).toBe("0.000");
  });

  it("gives null for anything that is not a quantity", () => {
    expect(rowQuantity(row("two"))).toBeNull();
    expect(rowQuantity(row("1", "1.2345"))).toBeNull(); // more than 3 decimals
    expect(rowQuantity(row("0"))).toBeNull();
    expect(measuredTotal([row("1"), row("x")])).toBeNull();
  });
});
