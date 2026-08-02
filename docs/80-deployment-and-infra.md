# Doc 80 — Deployment & Infrastructure

> How to host, configure, and go live — including Meta setup, data loads, pilot, and backups.
> Related: [20 Backend](20-backend-architecture.md) · [10 Cloud API](10-whatsapp-cloud-api.md) · [70 Security](70-security-and-compliance.md)

> **⚠️ Updated for the chosen stack (wacrm + self-hosted Supabase).** Sections below written for
> the original Express+RDS+Redis plan are superseded by this: we deploy the **wacrm Next.js app**
> plus a **self-hosted Supabase Docker stack** (Postgres + Auth + RLS + Realtime + Storage) on a
> **Hostinger VPS** (Docker required — the shared "Managed Node.js" plan can't run the Supabase
> stack). Data stays entirely on A7's server. Setup: [Doc 92 §2b](92-local-setup-guide.md). This
> doc gets a fuller rewrite when we harden deployment; the Meta/go-live/pilot/backup steps below
> remain valid as-is.
>
> **Server components:** (1) self-hosted Supabase stack (Docker Compose), (2) wacrm Next.js app,
> (3) n8n for Bitrix glue, (4) media served via Supabase Storage. No separate Postgres/Redis to
> manage — Supabase provides Postgres; wacrm uses `after()`/cron instead of a Redis queue.

---

## 1. Components to run

| Component | What | Notes |
|-----------|------|-------|
| **Backend (Node)** | API + webhook + Socket.IO + workers | 1 process (or split web/worker later) |
| **PostgreSQL** | main DB | managed (RDS) or on the VPS |
| **Redis** | BullMQ queue | optional early; needed for robust workers |
| **Media storage** | files | local disk driver on VPS, or S3 / Cloudflare R2 |
| **n8n** | Bitrix glue | already owned |
| **Web app (static)** | React build | served via Nginx / CDN / static host |
| **Reverse proxy** | Nginx | TLS termination, routes `/api`, `/webhook`, socket, static |

---

## 2. Two hosting paths

### Path A — Hostinger VPS (single box, simplest)
- One VPS runs: Nginx + Node backend + PostgreSQL + Redis + n8n; media on local disk.
- Cheapest, fine for the pilot and early production.
- Ensure: enough RAM for Node + Postgres + Redis; daily off-box backups.

### Path B — AWS (same env as Bitrix, more scalable)
- Backend on **Lightsail/EC2**, PostgreSQL on **RDS**, media on **S3**, Redis on ElastiCache.
- Scales cleaner; costs more.

> The **storage driver** and config make A ↔ B a config change, not a rewrite. Start on
> whichever is ready; the code doesn't care.

---

## 3. Networking & TLS

- A domain (e.g. `app.a7group...`) with **HTTPS** (Let's Encrypt / ACM).
- Nginx routes:
  - `/webhook/whatsapp` → backend (raw body preserved for signature).
  - `/api/*` → backend.
  - `/socket.io/*` → backend (WebSocket upgrade enabled).
  - everything else → static web app.
- The webhook URL **must be public HTTPS** for Meta.

---

## 4. Configuration (env)

Provide `.env` (git-ignored) with all secrets from [Doc 70](70-security-and-compliance.md) §2, plus:
```
NODE_ENV=production
PORT=8080
PUBLIC_URL=https://app.a7group.example
STORAGE_DRIVER=local            # local | s3 | r2
STORAGE_PATH=/var/a7/media      # for local
# S3/R2 creds when STORAGE_DRIVER != local
```

---

## 5. Meta / WhatsApp go-live steps

1. Register the **production webhook URL** in Meta Business Manager; subscribe `messages`.
2. Confirm the **permanent System-User token** + `WA_APP_SECRET` + `WA_VERIFY_TOKEN`.
3. Add all **phone numbers** (PNIDs) into `whatsapp_numbers` ([Doc 11](11-multi-number-management.md)).
4. Submit all **templates** and wait for approval (allow 1–2 days; [Doc 12](12-window-and-templates.md)).
5. **Confirm current UAE pricing** in Business Manager → set rates in config ([Doc 53](53-cost-control.md)).
6. Verify a real inbound → app → dashboard → Bitrix round-trip.

---

## 6. Data loads

- **Competitor DB:** import the real 30k–100k CSV (normalise E.164, `COPY`/batch, dedupe) — [Doc 52](52-competitor-detection.md).
- **Agents:** create accounts, assign teams/communities, set roles.
- **Leads (if importing for outreach):** import with correct **consent source** so `consent_state`
  is set right on import ([Doc 13](13-consent-and-ban-safety.md)).
- Seed `settings` (hot threshold, caps, window hours) and the 5 templates.

---

## 7. Media size limits (Meta) — validate on upload

Enforce Meta's per-type limits when agents attach files (reject oversized with a clear message):
images/documents/audio/video each have a max size — read the current limits from Meta docs at
build time and put them in config. Store only what Meta will accept.

---

## 8. Rollout plan

1. **Pilot:** 3–5 agents for **one week**. Watch number health, delivery, AI accuracy, adoption.
2. Fix issues; tune hot threshold, warm-up, pacing.
3. **Full rollout:** onboard all agents; assign communities/numbers.
4. **Mandate:** once stable, require the web app and **disable personal-WhatsApp** use for
   company customers via the signed agent policy.

---

## 9. Backups & DR

- **PostgreSQL:** automated daily backups + point-in-time if possible; **test restores**.
- **Media:** backup the storage (S3 versioning, or off-box copy for VPS disk).
- **Config/secrets:** stored securely (secret manager / sealed), recoverable.
- Documented **restore runbook**; know your RPO/RTO.

---

## 10. Monitoring & ops

- **Uptime** monitor on `/webhook/whatsapp` health + API.
- **Error tracking** (e.g. Sentry) on backend + web app.
- **Queue health:** watch job backlog, retries, dead-letters.
- **Per-number alerts:** quality → Red, number restricted, delivery failure spike ([Doc 11](11-multi-number-management.md), [Doc 13](13-consent-and-ban-safety.md)).
- **Cost watch:** monthly spend + budget alerts ([Doc 53](53-cost-control.md)).
- Log rotation; no secrets/PII in logs ([Doc 70](70-security-and-compliance.md)).

---

## 11. CI/CD (recommended)

- Git repo, feature branches, PR review.
- Pipeline: install → typecheck/lint → test → build → deploy.
- **DB migrations run as a deploy step** (never hand-edit prod).
- Rollback plan: keep the previous build + a reversible migration strategy.

---

## 12. Go-live checklist (master — pairs with Section 16 of the original spec)

- [ ] HTTPS domain live; webhook registered + verified.
- [ ] Forged webhook rejected (signature).
- [ ] Inbound message → agent app in seconds.
- [ ] Reply delivers from the **company number** (not personal).
- [ ] Message appears in dashboard live + in Bitrix.
- [ ] 24h close disables free-text + shows templates; one tap re-opens.
- [ ] AI score updates; hot-lead alert fires once on crossing.
- [ ] Competitor banner instant; duplicate alert works.
- [ ] Agent sees only own chats; manager sees team.
- [ ] Media inbound/outbound works within size limits.
- [ ] Cost report shows free vs paid.
- [ ] No API key anywhere in web app / CRM.
- [ ] Backups taken **and** a restore tested.
- [ ] Competitor DB + agents + templates + rates loaded.
- [ ] Pilot (3–5 agents) passed one week before full rollout.

---

*End of documentation set. Back to the [Master Concept Document](00-system-concepts.md).*
