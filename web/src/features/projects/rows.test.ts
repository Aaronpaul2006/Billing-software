import { describeRowError } from "./rows";

describe("describeRowError", () => {
  it.each([
    ["rows[7].rate", "Row 7 · rate"],
    ["rows[12].item_code", "Row 12 · item_code"],
    ["rows[3]", "Row 3"],
    ["file", "file"],
    [null, "File"],
  ])("%s -> %s", (field, text) => {
    expect(describeRowError(field)).toBe(text);
  });
});
