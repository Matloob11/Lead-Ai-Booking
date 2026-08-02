# Doc 70 — Security & Compliance

> Cross-cutting rules every module must follow. Covers secrets, auth, webhook integrity,
> data protection (UAE **PDPL**), telemarketing (**TDRA**), and retention.
> Related: [20 Backend](20-backend-architecture.md) · [10 Cloud API](10-whatsapp-cloud-api.md) · [13 Consent](13-consent-and-ban-safety.md) · [50 AI](50-ai-intelligence.md)

---

## 1. The one hard rule

**No WhatsApp API key, app secret, OpenAI key, or Bitrix webhook ever leaves the backend.**
The web app and CRM never hold a secret and never call Meta directly. This is what keeps A7 in
control of the number and the data — and stops any agent taking either with them.

---

## 2. Secrets management

- All secrets are **backend environment variables / a secret store** — never in code, never in
  the repo, never in the browser bundle.
- Secrets inventory: `WA_PERMANENT_TOKEN`, `WA_APP_SECRET`, `WA_VERIFY_TOKEN`, `OPENAI_API_KEY`,
  `BITRIX_WEBHOOK_URL`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, storage keys.
- **Rotation:** if any secret leaks, rotate immediately (WhatsApp token in Meta Business Manager).
  Keep rotation quick — no secret hard-coded anywhere.
- `.env` is git-ignored; provide a `.env.example` with keys only, no values.

---

## 3. Authentication & authorization

- **Login:** email + password (hashed with bcrypt/argon2). No WhatsApp key on the client.
- **JWT:** short-lived access token + refresh; payload carries `role` + `agentId` + `teamId`.
- **RBAC / least access (enforced server-side):**
  - `agent` → only `assigned_agent_id = self` data.
  - `manager` → only their `teamId`.
  - `admin` → everything.
- The **client is never trusted** for scope — every query/socket room is filtered on the server.
- Optional: 2FA for admin/manager accounts.

---

## 4. Webhook integrity

- **Meta:** verify `X-Hub-Signature-256` (HMAC-SHA256 with `WA_APP_SECRET`) over the **raw body**
  on every POST; reject mismatches (401). ([Doc 10](10-whatsapp-cloud-api.md) §4.1)
- **Bitrix:** validate the inbound webhook token/secret before acting.
- **Idempotency:** dedupe by `wa_message_id` so replays can't inject/duplicate.

---

## 5. Transport & storage security

- **HTTPS everywhere** (TLS). No plain HTTP endpoints.
- **At rest:** DB on a private network; **media** access-controlled (signed URLs or auth-gated
  proxy — media is not public). Backups encrypted.
- **PII minimisation:** store only what's needed; don't log message bodies or tokens in plain logs.
- **Rate limiting** on auth + public endpoints; lockout/backoff on brute force.
- **Input validation** (Zod) on every external input (webhooks + API).

---

## 6. UAE PDPL (Personal Data Protection Law)

Customer numbers, names, and chats are **personal data**. Obligations to honour:

- **Lawful basis:** consent or legitimate interest for processing ([Doc 13](13-consent-and-ban-safety.md)).
- **Purpose limitation:** data used for the customer relationship + service, not resold/misused.
- **Third-party processing:** sending chat text to **OpenAI** is processing by a sub-processor —
  send the **minimum**, avoid documents/IDs, and record it. ([Doc 50](50-ai-intelligence.md) §9)
- **Data subject rights:** be able to **export** and **delete** a customer's data on request.
- **Retention:** define how long messages/scores are kept; purge or archive after that.

---

## 7. TDRA (telemarketing) & the competitor DB

- **Cold outreach** must respect TDRA rules: opt-in where required, honour opt-out (STOP),
  no unsolicited marketing spam. ([Doc 13](13-consent-and-ban-safety.md))
- The **competitor-agent database** is **defensive only** — used to recognise who is contacting
  us and protect owners. It must **never** be used as a marketing list. ([Doc 52](52-competitor-detection.md) §8)

---

## 8. Audit & accountability

- **Append-only `audit_log`** for every meaningful action: login, send, send-template, reassign,
  competitor import, whitelist, settings change, export ([Doc 30](30-database-schema.md) §2.11).
- Outreach sends record their **consent basis** (why it was allowed).
- Exports (conversations/reports) are themselves audited.

---

## 9. Data retention policy (define at go-live)

| Data | Suggested retention (confirm with A7 legal) |
|------|---------------------------------------------|
| Messages / media | keep active + N months, then archive/purge |
| AI raw JSON (`ai_scores.raw`) | shorter — it's derived; purge sooner |
| Audit log | longer — accountability |
| Opt-out records | keep (must not re-contact) |

Retention is enforced by a scheduled purge job; opt-out list is exempt from deletion.

---

## 10. Operational security

- Least-privilege DB users; separate app vs migration credentials.
- Dependencies scanned/updated; no secrets in CI logs.
- Backups tested (restore drills), not just taken. ([Doc 80](80-deployment-and-infra.md))
- Monitoring + alerting on errors, auth anomalies, and per-number restrictions.

---

## 11. Security testing checklist

- [ ] No secret appears in the web app / CRM bundle or the repo.
- [ ] Forged Meta webhook (bad signature) rejected.
- [ ] Agent cannot access another agent's data via API or socket (tested, not assumed).
- [ ] All traffic is HTTPS; media is not publicly listable.
- [ ] Passwords hashed; JWT expiry + refresh work; optional admin 2FA.
- [ ] Opt-out (STOP) permanently blocks outreach.
- [ ] Customer data export + delete works (PDPL rights).
- [ ] Retention purge runs; opt-out records survive it.
- [ ] Every sensitive action writes an audit row.

---

*Next: [Doc 80 — Deployment & Infrastructure](80-deployment-and-infra.md).*
