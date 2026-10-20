import { cleanMoneyInput, formatInr, formatQty, groupIndian, MONEY_INPUT } from "./money";

describe("groupIndian", () => {
  it.each([
    ["0", "0"],
    ["999", "999"],
    ["1000", "1,000"],
    ["341020", "3,41,020"],
    ["34102000", "3,41,02,000"],
    ["1234567890", "1,23,45,67,890"],
  ])("%s -> %s", (digits, grouped) => {
    expect(groupIndian(digits)).toBe(grouped);
  });
});

describe("formatInr", () => {
  it.each([
    ["341020.00", "₹3,41,020.00"],
    ["323680.00", "₹3,23,680.00"],
    ["-8024.00", "-₹8,024.00"],
    ["0.00", "₹0.00"],
    ["7", "₹7.00"],
    ["7.5", "₹7.50"],
    ["0012.30", "₹12.30"],
    ["10000000.00", "₹1,00,00,000.00"],
  ])("%s -> %s", (amount, shown) => {
    expect(formatInr(amount)).toBe(shown);
  });

  it("never rounds: extra decimals are shown, not dropped", () => {
    expect(formatInr("1.005")).toBe("₹1.005");
  });

  it("leaves anything else alone and handles empty values", () => {
    expect(formatInr("abc")).toBe("abc");
    expect(formatInr(null)).toBe("");
    expect(formatInr("")).toBe("");
    expect(formatInr("1500.00", { symbol: false })).toBe("1,500.00");
  });

  it("keeps paise exact where floats would not", () => {
    // 0.1 + 0.2 style errors cannot happen: no arithmetic on amounts.
    expect(formatInr("99999999999.99")).toBe("₹99,99,99,99,999.99");
  });
});

describe("formatQty", () => {
  it.each([
    ["42.500", "42.5"],
    ["120.000", "120"],
    ["1250.750", "1,250.75"],
    ["0.001", "0.001"],
  ])("%s -> %s", (qty, shown) => {
    expect(formatQty(qty)).toBe(shown);
  });
});

describe("money input", () => {
  it("cleans and validates", () => {
    expect(cleanMoneyInput("₹ 1,23,456.50")).toBe("123456.50");
    expect(MONEY_INPUT.test("123456.50")).toBe(true);
    expect(MONEY_INPUT.test("1.505")).toBe(false);
    expect(MONEY_INPUT.test("-5")).toBe(false);
  });
});
