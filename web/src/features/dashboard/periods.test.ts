import { formatRange, fyStartYear, periodRange } from "./periods";

const day = (y: number, m: number, d: number) => new Date(y, m - 1, d);

describe("financial-year periods", () => {
  it("April starts the financial year; January to March belong to the previous one", () => {
    expect(fyStartYear(day(2026, 4, 1))).toBe(2026);
    expect(fyStartYear(day(2026, 10, 20))).toBe(2026);
    expect(fyStartYear(day(2027, 3, 31))).toBe(2026);
    expect(fyStartYear(day(2027, 1, 1))).toBe(2026);
  });

  it.each([
    ["this_month", day(2026, 10, 20), { from: "2026-10-01", to: "2026-10-20" }],
    ["last_month", day(2026, 10, 20), { from: "2026-09-01", to: "2026-09-30" }],
    ["last_month", day(2027, 1, 15), { from: "2026-12-01", to: "2026-12-31" }],
    ["last_month", day(2028, 3, 10), { from: "2028-02-01", to: "2028-02-29" }],
    ["this_fy", day(2026, 10, 20), { from: "2026-04-01", to: "2026-10-20" }],
    ["this_fy", day(2027, 2, 5), { from: "2026-04-01", to: "2027-02-05" }],
    ["last_fy", day(2026, 10, 20), { from: "2025-04-01", to: "2026-03-31" }],
  ] as const)("%s on %s", (key, today, range) => {
    expect(periodRange(key, today)).toEqual(range);
  });

  it("formats ranges", () => {
    expect(formatRange("2026-10-01", "2026-10-20")).toBe("1 Oct – 20 Oct 2026");
    expect(formatRange("2025-04-01", "2026-03-31")).toBe("1 Apr 2025 – 31 Mar 2026");
  });
});
