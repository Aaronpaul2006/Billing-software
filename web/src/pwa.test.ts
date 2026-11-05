import manifestText from "../public/manifest.webmanifest?raw";
import swSource from "../public/sw.js?raw";

/** The files in public/icons, by the path the manifest uses ("/icons/icon-192.png"). */
const ICONS = new Set(
  Object.keys(import.meta.glob("../public/icons/*")).map((p) => p.replace("../public", "")),
);

type Kind = (url: URL, origin: string, mode: string, method: string) => string;

/** The routing rule of public/sw.js, without running a service worker. */
function loadKind(): Kind {
  const body = swSource.slice(
    swSource.indexOf("function kind("),
    swSource.indexOf("async function trim("),
  );
  // public/sw.js is a plain script (not a module), so its rule is read out of the file
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  const make = new Function(`${body}; return kind;`) as () => Kind;
  return make();
}

describe("installable app (D.14)", () => {
  const ORIGIN = "https://app.example.in";
  const at = (p: string) => new URL(p, ORIGIN);

  it("never keeps API data; keeps the app's own files", () => {
    const kind = loadKind();
    expect(kind(at("/api/v1/documents"), ORIGIN, "cors", "GET")).toBe("skip");
    expect(kind(at("/api/v1/documents/x/pdf"), ORIGIN, "navigate", "GET")).toBe("skip");
    expect(kind(at("/api/v1/auth/token/refresh"), ORIGIN, "cors", "POST")).toBe("skip");
    expect(kind(at("/assets/index-abc123.js"), ORIGIN, "no-cors", "GET")).toBe("asset");
    expect(kind(at("/icons/icon-192.png"), ORIGIN, "no-cors", "GET")).toBe("asset");
    expect(kind(at("/documents/123"), ORIGIN, "navigate", "GET")).toBe("page");
    expect(kind(new URL("https://s3.example/bill.pdf"), ORIGIN, "cors", "GET")).toBe("skip");
    expect(kind(at("/assets/x.js"), ORIGIN, "no-cors", "POST")).toBe("skip");
  });

  it("has a manifest whose icons exist", () => {
    const manifest = JSON.parse(manifestText) as {
      start_url: string;
      display: string;
      icons: { src: string; purpose?: string }[];
    };
    expect(manifest.start_url).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
    for (const icon of manifest.icons) {
      expect(ICONS.has(icon.src)).toBe(true);
    }
  });
});
