const express = require("express");
const cors = require("cors");
const morgan = require("morgan");
const http = require("http");
const path = require("path");

const app = express();
const PORT = process.env.PORT || 3000;
const PYTHON_API_URL = process.env.PYTHON_API_URL || "http://api:8000";
const parsed = new URL(PYTHON_API_URL);
const PYTHON_HOST = parsed.hostname;
const PYTHON_PORT = parseInt(parsed.port) || 8000;

app.use(cors());
app.use(morgan("combined"));

// Serve the UI
app.use(express.static(path.join(__dirname, "public")));

app.get("/health", (req, res) => {
  res.json({ status: "ok", service: "express-gateway", uptime: process.uptime() });
});

// Proxy /api/* to Python FastAPI
app.use((req, res, next) => {
  if (!req.originalUrl.startsWith("/api")) return next();

  const options = {
    hostname: PYTHON_HOST,
    port: PYTHON_PORT,
    path: req.originalUrl,
    method: req.method,
    headers: { ...req.headers, host: `${PYTHON_HOST}:${PYTHON_PORT}` },
  };

  const proxy = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxy.on("error", (err) => {
    console.error("[Proxy Error]", err.message);
    res.status(502).json({ error: "Python API unreachable", detail: err.message });
  });

  req.pipe(proxy, { end: true });
});

// Fallback to UI
app.get("*", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(PORT, () => {
  console.log(`🚀 Express Gateway on port ${PORT}`);
  console.log(`🎨 UI available at http://localhost:${PORT}`);
  console.log(`🔗 Proxying /api/* to ${PYTHON_API_URL}`);
});
