# Doc 20 — Backend Architecture

> The backend is the **only** component that holds secrets and talks to Meta, OpenAI, and
> Bitrix24. It is the brain: webhook intake, routing, detection, AI, CRM sync, realtime,
> auth, admin. This doc defines its modules, APIs, data flow, and background jobs.
> Related: [10 Cloud API](10-whatsapp-cloud-api.md) · [30 DB schema](30-database-schema.md) · [40 Frontend](40-frontend-web-app.md)

---

## 1. Tech stack

| Concern | Choice | Why |
|---------|--------|-----|
| Runtime | **Node.js (LTS)** | Huge talent pool, great WhatsApp/Bitrix/OpenAI SDK support |
| HTTP framework | **Express** (or NestJS if the team prefers structure) | Simple REST + raw-body control for webhook signature |
| Realtime | **Socket.IO** | Live push to web app + dashboard, auto-reconnect/fallback |
| DB | **PostgreSQL** | Reliable, relational, handles message + 100k-number volume |
| DB access | **Prisma** or **Knex** | Migrations + typed queries |
| Queue | **BullMQ (Redis)** | Background jobs so webhooks return fast |
| Auth | **JWT** (access + refresh) | Stateless web-app login, role claims |
| Validation | **Zod** | Validate inbound payloads + API bodies |
| HTTP client | **axios / undici** | Calls to Meta Graph, OpenAI, Bitrix |

> If the team wants to avoid Redis early, the queue can start as an in-process job runner and
> graduate to BullMQ/Redis later. Design the worker interface so this swap is painless.

---

## 2. High-level shape

```
                         ┌─────────────────────────── BACKEND ───────────────────────────┐
   Meta  ──webhook──►    │  webhook route ─► signature verify ─► enqueue ─► 200 OK         │
                         │                                          │                       │
   Web app ──REST/WS──►  │  API routes (auth+role) ── services ─────┤                       │
                         │                                          ▼                       │
                         │   WORKERS: message · detection · ai · bitrix · media · outreach  │
                         │        │            │        │       │        │        │          │
                         └────────┼────────────┼────────┼───────┼────────┼────────┼──────────┘
                                  ▼            ▼        ▼       ▼        ▼        ▼
                              Postgres    competitor  OpenAI  Bitrix  storage  Meta send
                                          index                (n8n)   (S3/disk)
                                  │
                                  ▼  Socket.IO push  ─►  agents + managers (live)
```

---

## 3. Modules (responsibilities)

### 3.1 Webhook module
- `GET /webhook/whatsapp` — verification challenge ([Doc 10](10-whatsapp-cloud-api.md) §3).
- `POST /webhook/whatsapp` — verify `X-Hub-Signature-256` over **raw body**, dedupe by `wamid`,
  enqueue, return 200 fast.
- Splits payload into **inbound messages** vs **status callbacks** and routes each to its job.

### 3.2 Message service
- Persist inbound/outbound messages; resolve customer, number, agent ([Doc 11](11-multi-number-management.md)).
- Maintain `last_inbound_at` (window state, [Doc 12](12-window-and-templates.md)).
- Send outbound: decide free-form vs template, call Meta via the correct PNID, store `wamid`.
- Apply status callbacks to stored messages (sent → delivered → read → failed).

### 3.3 Number router / assignment engine
- Inbound routing + outbound number selection + new-lead assignment ([Doc 11](11-multi-number-management.md) §3–5).

### 3.4 Template service
- List approved templates, fill variables, pick variant, build Meta template payload ([Doc 12](12-window-and-templates.md)).

### 3.5 Detection pipeline
Runs on each inbound (in the worker), in order:
1. **Competitor check** — number vs indexed competitor DB ([Doc 52](52-competitor-detection.md)).
2. **Duplicate check** — number vs other active conversations ([Doc 51](51-duplicate-detection.md)).
3. **AI scoring** (batched) — sentiment/seriousness/intent/behaviour ([Doc 50](50-ai-intelligence.md)).
Each produces flags/scores → stored → pushed to UI → written to Bitrix.

### 3.6 AI service
- Build conversation context, call OpenAI, validate JSON, store scores, fire hot-lead alerts ([Doc 50](50-ai-intelligence.md)).

### 3.7 Bitrix sync service
- Upsert contact, attach chat/timeline, write custom fields, move deals — direct REST or via n8n ([Doc 60](60-bitrix24-sync.md)).

### 3.8 Realtime gateway (Socket.IO)
- Auth the socket with the JWT; join rooms (`agent:{id}`, `team:{id}`, `admin`).
- Emit `message:new`, `message:status`, `lead:scored`, `alert:*`, `number:health`.

### 3.9 Auth & RBAC
- Login, refresh, logout; issue JWT with `role` + `agentId`.
- Middleware enforces **least access** (agent → own chats only). See §6.

### 3.10 Admin service
- Manage numbers, templates, competitor DB, thresholds, agents, re-assignment, exports.

### 3.11 Outreach engine
- Consent-checked, rate-limited cold outreach batches ([Doc 13](13-consent-and-ban-safety.md) §8).

### 3.12 Audit + alerts
- Append-only `audit_log` for every action; `alerts` table + realtime feed.

---

## 4. Background workers (queues)

| Queue | Triggered by | Does |
|-------|--------------|------|
| `inbound` | webhook | persist message, run detection pipeline, push to UI |
| `status` | webhook | update message delivery state, push to UI |
| `ai` | inbound (batched) | OpenAI scoring, alerts |
| `bitrix` | message/lead events | CRM upserts (retry on failure) |
| `media` | inbound/outbound media | download from Meta / upload to Meta + store |
| `outreach` | admin campaign / schedule | paced, consent-checked template sends |

**Why queues:** webhooks must return in seconds; heavy work (AI, CRM, media) runs async with
**retries + backoff**, so a slow Bitrix or OpenAI never blocks message intake.

---

## 5. REST API surface (for the web app)

> All under `/api`, JWT-protected, role-checked. Full request/response shapes live with each feature doc; this is the map.

**Auth**
- `POST /api/auth/login` · `POST /api/auth/refresh` · `POST /api/auth/logout`

**Chats & messages (agent + manager)**
- `GET  /api/chats` — list assigned chats (agent = own; manager = team) + flags + window state
- `GET  /api/chats/:customerId/messages` — paginated history
- `POST /api/chats/:customerId/send` — free-form text/media (backend enforces window)
- `POST /api/chats/:customerId/send-template` — template send
- `POST /api/chats/:customerId/read` — mark read
- `GET  /api/customers/:id` — customer card (name, budget, community, Bitrix link, flags)

**Manager / dashboard**
- `GET /api/dashboard/live` · `GET /api/dashboard/hot-leads` · `GET /api/alerts`
- `GET /api/agents/scoreboard` · `GET /api/numbers/health` · `GET /api/search?q=`

**Admin**
- `POST /api/admin/numbers` … `PATCH /api/admin/numbers/:id` (pause/resume/assign)
- `POST /api/admin/templates` … submit/enable
- `POST /api/admin/competitors/import` (CSV) · `POST /api/admin/competitors/whitelist`
- `POST /api/admin/agents` · `POST /api/admin/reassign` · `GET /api/admin/export`
- `PATCH /api/admin/settings` (hot-lead threshold, pacing, etc.)

**Webhooks (external)**
- `GET|POST /webhook/whatsapp` (Meta) · `POST /webhook/bitrix` (Bitrix → us, optional two-way)

---

## 6. Auth & role enforcement (least access)

- JWT payload: `{ sub: agentId, role: 'agent'|'manager'|'admin', teamId }`.
- **Data scoping is server-side**, never trusted from the client:
  - `agent` → queries always filtered to `assigned_agent_id = self`.
  - `manager` → filtered to their `teamId`.
  - `admin` → unrestricted.
- Socket.IO rooms mirror the same scoping so realtime pushes respect roles.

---

## 7. Config & secrets

All secrets are backend env vars (see per-doc lists): WhatsApp token/app-secret/verify-token,
OpenAI key, Bitrix webhook, DB URL, Redis URL, JWT secret, storage credentials. **Nothing
secret reaches the browser.** ([Doc 70](70-security-and-compliance.md))

---

## 8. Suggested folder structure

```
src/
  webhook/         # meta verify + receive + signature
  messages/        # message service, window logic
  numbers/         # registry + router + assignment engine
  templates/       # template service
  detection/       # competitor + duplicate
  ai/              # openai service
  bitrix/          # crm sync
  outreach/        # cold outreach engine
  realtime/        # socket.io gateway
  auth/            # jwt + rbac
  admin/           # admin endpoints
  storage/         # media driver (local | s3 | r2)
  queue/           # bullmq workers
  db/              # prisma/knex + migrations
  common/          # config, logging, errors, validation (zod)
  http/            # express app + routes wiring
```

---

## 9. Non-functional requirements

- **Fast webhook ack** (<3s) via enqueue-then-process.
- **Idempotency** everywhere Meta can retry (dedupe by `wamid`).
- **Retries with backoff** for AI/Bitrix/media/send.
- **Structured logging** + request IDs; errors surfaced to admin, not customers.
- **Rate limiting** on public + auth endpoints.
- **Graceful degradation:** if OpenAI/Bitrix is down, messaging still works; scoring/sync retry later.

---

## 10. Testing checklist

- [ ] Webhook returns 200 in <3s under load (heavy work is queued).
- [ ] Signature verification rejects forged POSTs.
- [ ] Duplicate `wamid` never double-inserts.
- [ ] Agent API calls only ever return that agent's data.
- [ ] Manager sees team scope; admin sees all.
- [ ] Socket rooms respect roles (no cross-agent leakage).
- [ ] OpenAI/Bitrix outage does not block send/receive; jobs retry.
- [ ] Outbound uses the correct number + enforces the window.

---

*Next: [Doc 30 — Database Schema](30-database-schema.md).*
