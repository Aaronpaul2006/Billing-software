import {
  cleanMoneyInput,
  compareMoney,
  fillInOrder,
  formatInr,
  formatQty,
  fromPaise,
  groupIndian,
  MONEY_INPUT,
  percentOf,
  qtyTimesRate,
  subtractMoney,
  sumMoney,
  toPaise,
} from "./money";

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

describe("exact paise arithmetic", () => {
  it("parses and prints amounts exactly", () => {
    expect(toPaise("1234.5")).toBe(123450n);
    expect(toPaise("₹ 3,23,680.00")).toBe(32368000n);
    expect(toPaise("0.1")).toBe(10n);
    expect(toPaise("1.005")).toBeNull(); // no third decimal for money
    expect(toPaise("abc")).toBeNull();
    expect(fromPaise(32368000n)).toBe("323680.00");
    expect(fromPaise(-5n)).toBe("-0.05");
  });

  it("adds without float errors", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30"); // 0.1 + 0.2 = 0.30000000000000004 in floats
    expect(sumMoney(["99999999999.99", "0.01"])).toBe("100000000000.00");
    expect(sumMoney(["", "5"])).toBe("5.00");
    expect(sumMoney(["5", "x"])).toBeNull();
    expect(subtractMoney("300000", "323680.00")).toBe("-23680.00");
    expect(compareMoney("10.00", "9.99")).toBe(1);
    expect(compareMoney("10", "10.00")).toBe(0);
  });

  it("fills the oldest first", () => {
    expect(fillInOrder("400000", ["323680.00", "10600.00", "8024.00"])).toEqual([
      "323680.00",
      "10600.00",
      "8024.00",
    ]);
    expect(fillInOrder("330000", ["323680.00", "10600.00", "8024.00"])).toEqual([
      "323680.00",
      "6320.00",
      "",
    ]);
    expect(fillInOrder("0", ["5.00"])).toEqual([""]);
  });
});

describe("qtyTimesRate and percentOf (RA bills)", () => {
  it("multiplies exactly and rounds half up to the paisa", () => {
    expect(qtyTimesRate("40", "4000")).toBe("160000.00");
    expect(qtyTimesRate("12.345", "333.33")).toBe("4114.96"); // 4114.95885
    expect(qtyTimesRate("0.005", "1.00")).toBe("0.01"); // 0.005 rounds up
    expect(qtyTimesRate("1.2345", "10")).toBeNull(); // 4 decimals
    expect(qtyTimesRate("", "10")).toBeNull();
  });
  it("takes a percentage, to the paisa or the rupee", () => {
    expect(percentOf("220000.00", "18")).toBe("39600.00");
    expect(percentOf("220000.00", "5")).toBe("11000.00");
    expect(percentOf("12345.67", "1", true)).toBe("123.00"); // 123.4567 -> 123
    expect(percentOf("12350.00", "1", true)).toBe("124.00"); // 123.50 -> 124
    expect(percentOf("100.00", "2.5")).toBe("2.50");
  });
});
