import { applyAppearance, setTextSize, setThemeChoice, textSize, themeChoice } from "./appearance";

const html = document.documentElement;

afterEach(() => {
  window.localStorage.clear();
  html.className = "";
  vi.unstubAllGlobals();
});

describe("appearance (D.2)", () => {
  it("follows the device by default, with normal text", () => {
    expect(themeChoice()).toBe("system");
    expect(textSize()).toBe("normal");
    applyAppearance();
    expect(html.classList.contains("dark")).toBe(false);
    expect(html.classList.contains("text-large")).toBe(false);
  });

  it("follows a dark device when set to the device", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("dark"),
      addEventListener: () => undefined,
    }));
    applyAppearance();
    expect(html.classList.contains("dark")).toBe(true);
  });

  it("remembers dark and large text, and switches back", () => {
    setThemeChoice("dark");
    setTextSize("large");
    expect(html.classList.contains("dark")).toBe(true);
    expect(html.classList.contains("text-large")).toBe(true);
    expect(themeChoice()).toBe("dark");
    setThemeChoice("light");
    setTextSize("normal");
    expect(html.className).toBe("");
  });

  it("still works when the browser blocks storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(themeChoice()).toBe("system");
    expect(() => {
      setThemeChoice("dark");
    }).not.toThrow();
  });
});
