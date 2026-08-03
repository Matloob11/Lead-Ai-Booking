/**
 * Express REST API Server
 */

import express from "express";
import path from "node:path";

import sessionsRouter from "./routes/sessions.js";
import conversationsRouter from "./routes/conversations.js";
import sendRouter from "./routes/send.js";
import mediaRouter from "./routes/media.js";

export function startApi(port = 8300) {
  const app = express();

  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // CORS headers
  app.use((req, res, next) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
    if (req.method === "OPTIONS") return res.status(200).end();
    next();
  });

  // Health check
  app.get("/healthz", (req, res) => {
    res.json({ status: "ok" });
  });

  // Routes
  app.use("/api/sessions", sessionsRouter);
  app.use("/api/conversations", conversationsRouter);
  app.use("/api/send", sendRouter);
  app.use("/api/media", mediaRouter);

  // Static UI files (served for Agent 3's UI)
  app.use(express.static(path.resolve("public")));

  // Global Error Handler
  app.use((err, req, res, _next) => {
    console.error(`[wa-qr] API error on ${req.method} ${req.url}:`, err);
    res.status(err.status || 500).json({
      detail: err.message || "Internal server error",
    });
  });

  const server = app.listen(port, () => {
    console.info(`[wa-qr] API server listening on http://127.0.0.1:${port}`);
  });

  return server;
}
