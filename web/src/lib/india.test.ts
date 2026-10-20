import spec from "../../../backend/openapi.json";

import { STATES } from "./india";

describe("STATES", () => {
  it("matches the API's state codes and names (backend/openapi.json)", () => {
    const typed = spec as unknown as {
      components: { schemas: { StateCodeEnum: { description: string } } };
    };
    const description = typed.components.schemas.StateCodeEnum.description;
    const fromApi = Object.fromEntries(
      [...description.matchAll(/`(\d{2})` - (.+)/g)].map((m): [string, string] => [
        m[1] ?? "",
        (m[2] ?? "").trim(),
      ]),
    );
    expect(STATES).toEqual(fromApi);
  });
});
