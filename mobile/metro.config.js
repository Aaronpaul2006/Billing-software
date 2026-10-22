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

const config = getDefaultConfig(__dirname);

config.server = {
  ...config.server,
  enhanceMiddleware: (metroMiddleware) => (req, res, next) => {
    if (req.url && req.url.startsWith("/api/")) return proxyToApi(req, res);
    return metroMiddleware(req, res, next);
  },
};

module.exports = config;
