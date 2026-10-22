/** "Chrome on Windows" from a browser's user agent; the label a device gave itself wins. */
export function describeDevice(userAgent: string | null, label: string | null): string {
  if (label) return label;
  if (!userAgent) return "Unknown device";
  const ua = userAgent;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\//.test(ua)
      ? "Opera"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Firefox\//.test(ua)
          ? "Firefox"
          : /Safari\//.test(ua)
            ? "Safari"
            : /okhttp|Dart|Expo|CFNetwork/i.test(ua)
              ? "App"
              : "Browser";
  // Order matters: Android says Linux, iPhone says "like Mac OS X".
  const os = /Android/.test(ua)
    ? "Android"
    : /iPhone|iPad|iOS/.test(ua)
      ? "iPhone"
      : /Windows/.test(ua)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(ua)
          ? "Mac"
          : /Linux/.test(ua)
            ? "Linux"
            : null;
  return os ? `${browser} on ${os}` : browser;
}
