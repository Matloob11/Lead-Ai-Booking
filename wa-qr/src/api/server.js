/**
 * Express REST API Server
 */

import express from "express";
import path from "node:path";

import { attachIdentity } from "./identity.js";
import sessionsRouter from "./routes/sessions.js";
import conversationsRouter from "./routes/conversations.js";
import sendRouter from "./routes/send.js";
import mediaRouter from "./routes/media.js";
import uploadRouter from "./routes/upload.js";
import actionsRouter from "./routes/actions.js";
import messagesRouter from "./routes/messages.js";

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

  // Everything under /api is somebody's private conversation, so nothing there
  // is served until nginx has said who is asking. The static panel below is
  // left open: it holds no data of its own, and a 401 on its first fetch says
  // what is wrong far more clearly than an empty screen would.
  app.use("/api", attachIdentity);

  // Who nginx says this is. The panel asks because some of what it draws is
  // admin-only — the buttons that link and unlink a phone — and a button that
  // is only going to answer 403 is worse than no button at all.
  app.get("/api/me", (req, res) => {
    res.json({ agent_id: req.identity.agentId, is_admin: req.identity.isAdmin });
  });

  // Routes
  app.use("/api/sessions", sessionsRouter);
  app.use("/api/conversations", conversationsRouter);
  app.use("/api/send", sendRouter);
  app.use("/api/media", mediaRouter);
  app.use("/api/upload", uploadRouter);
  app.use("/api/actions", actionsRouter);
  app.use("/api/messages", messagesRouter);

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
