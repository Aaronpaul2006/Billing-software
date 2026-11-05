import { formatDate, formatDateTime, formatDayMonth, formatMonthYear, formatTime } from "./dates";

describe("dates", () => {
  it("writes calendar days one way, never shifted by the time zone", () => {
    expect(formatDate("2026-10-25")).toBe("25 Oct 2026");
    expect(formatDate("2026-01-01")).toBe("1 Jan 2026");
    expect(formatDayMonth("2026-10-25")).toBe("25 Oct");
    expect(formatMonthYear("2026-10-01")).toBe("Oct 2026");
  });

  it("writes moments with the time, in 12-hour form", () => {
    const at = new Date(2026, 10, 4, 8, 21);
    expect(formatDateTime(at)).toBe("4 Nov 2026, 8:21 am");
    expect(formatTime(new Date(2026, 10, 4, 13, 5))).toBe("1:05 pm");
    expect(formatDate(at.toISOString())).toBe("4 Nov 2026");
  });

  it("shows a dash (or the given text) for no date", () => {
    expect(formatDate(null)).toBe("–");
    expect(formatDate(undefined, "")).toBe("");
    expect(formatDateTime("")).toBe("–");
  });
});
