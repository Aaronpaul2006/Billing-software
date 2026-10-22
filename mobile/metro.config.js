// Metro for the app, plus one development-only addition: when the app runs in
// a browser on the PC (`npx expo start --web`), requests to /api are passed to
// the Django API on 127.0.0.1:8000, so the browser sees one origin (no CORS),
// like the web app's Vite proxy. Phones call the API directly.
const http = require("node:http");

const { getDefaultConfig } = require("expo/metro-config");

const API = { host: "127.0.0.1", port: 8000 };

function proxyToApi(req, res) {
  const upstream = http.request(
    {
      ...API,
      method: req.method,
      path: req.url,
      headers: { ...req.headers, host: `${API.host}:${API.port}` },
    },
    (answer) => {
      res.writeHead(answer.statusCode ?? 502, answer.headers);
      answer.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.writeHead(502, { "Content-Type": "application/problem+json" });
    res.end(
      JSON.stringify({
        type: "about:blank",
        title: "API not running",
        status: 502,
        code: "api_unreachable",
        detail: "Start the API on 127.0.0.1:8000 (manage.py runserver).",
      }),
    );
  });
  req.pipe(upstream);
}

// Metro listens on every network interface; the API must not become reachable
// from the Wi-Fi through it. Only this PC may use the proxy (a phone on USB
// arrives as localhost through `adb reverse`; on Wi-Fi it calls the API itself).
function fromThisPc(req) {
  const address = req.socket.remoteAddress ?? "";
  return address === "127.0.0.1" || address === "::1" || address === "::ffff:127.0.0.1";
}

const config = getDefaultConfig(__dirname);

config.server = {
  ...config.server,
  enhanceMiddleware: (metroMiddleware) => (req, res, next) => {
    if (req.url && req.url.startsWith("/api/")) {
      if (fromThisPc(req)) return proxyToApi(req, res);
      res.writeHead(403, { "Content-Type": "text/plain" });
      return res.end("The /api proxy only serves this computer.");
    }
    return metroMiddleware(req, res, next);
  },
};

module.exports = config;
