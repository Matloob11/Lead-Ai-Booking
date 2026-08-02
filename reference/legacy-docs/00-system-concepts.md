# A7 Group — WhatsApp Lead-Control System

## Master Concept Document (v1.0)

> **Purpose of this document.** This is the single conceptual foundation for the whole
> project. It defines *every* concept, module, and rule in plain terms — no code yet.
> From this document we will spin off one detailed technical doc per area
> (frontend, backend, database, WhatsApp, CRM, AI, security, deployment).
>
> **Status of key decisions (confirmed 2026-07-15):**
> - WhatsApp access = **Official Meta Cloud API** (keys/Business-ID obtained via the
>   webbox/allots.io panel).
> - Frontend = **Web App** (browser, real-time, no page refresh). *No mobile app.*
> - **Multiple** WhatsApp numbers (per team/community/agent), not one company number.
> - Outreach = **both** cold (message new leads first) **and** incoming reply.
> - Media (photo/PDF/voice/video) = **in scope**, storage abstracted (local disk → S3/R2 swappable).
> - **Bitrix24** two-way sync = **in scope**. **OpenAI** for AI = **in scope**.

---

## 1. The System in One Page

A7 Group agents talk to real-estate customers on WhatsApp. Today they use their
**personal** numbers, so management is blind, leads get stolen when an agent leaves, and
two agents unknowingly chase the same client.

This system moves *every* customer conversation onto **company-owned WhatsApp numbers**,
routed through a **backend the company controls**. Managers watch everything live in a
**web dashboard**, the AI flags hot leads / competitors / duplicates, and everything is
mirrored into **Bitrix24** so the CRM stays the record of truth.

**The one hard rule:** the browser (agent web app) and the CRM **never** hold a WhatsApp
API key and **never** talk to Meta directly. Only the **backend** does. That is what keeps
the company in control of the number and the data.

```
Customer ⇄ WhatsApp (Meta Cloud API) ⇄  [BACKEND SERVER]  ⇄ Web App (agents + managers)
                                              │
                                              ├── PostgreSQL (messages, leads, flags)
                                              ├── OpenAI (sentiment / seriousness / intent)
                                              ├── Media storage (S3 / local disk)
                                              └── Bitrix24 (contacts, deals, timeline)  via n8n
```

---

## 2. Glossary — Core Terms

| Term | Meaning |
|------|---------|
| **Cloud API** | Meta's official WhatsApp Business Cloud API. We send/receive messages through it. |
| **WABA** | WhatsApp Business Account — the Meta container that owns the phone numbers. |
| **Phone Number ID** | Meta's internal ID for each WhatsApp number (used in API calls). One per number. |
| **Webhook** | A public HTTPS URL on our backend that Meta calls whenever a message/status event happens. |
| **Service / session message** | A free-form message allowed **only** inside the open 24-hour window. Free. |
| **Template message** | A pre-approved message required to start or re-open a chat outside the 24h window. Paid. |
| **24-hour window** | After a customer messages us, a 24h window opens in which we can reply free-form. |
| **Template category** | Meta classifies templates as **Utility**, **Marketing**, or **Authentication**. Different rules/cost. |
| **Opt-in** | The customer's consent to receive WhatsApp messages from us. Required before cold outreach. |
| **Quality rating** | Meta's per-number health score (Green/Yellow/Red), driven by user blocks/reports. Drives limits/bans. |
| **Messaging tier** | Per-number daily limit of unique customers we can start conversations with (250 → 1K → 10K → unlimited). |
| **Serious-lead score** | AI score 0–100 of how likely a customer is a real buyer/tenant. |
| **Duplicate client** | The same customer number active with more than one A7 agent at once. |
| **Competitor agent** | A caller who is a rival agent fishing for owner details, matched against our number database. |
| **Bitrix24** | A7's existing CRM — the permanent record of contacts, deals, and history. |

---

## 3. Actors & Roles

| Actor | What they are | Access |
|-------|---------------|--------|
| **Customer** | The person on WhatsApp (buyer/tenant/owner). | External. Only sees their chat with the agent via WhatsApp. |
| **Agent** | A7 sales agent. Works in the **web app**. | Sees **only their own** assigned chats. Can send messages/templates. |
| **Sales Manager** | Oversees a team/pod. | All chats of **their team** + alerts + stats. |
| **CEO / Admin (Malik)** | Owner / super-admin. | **Everything**, all teams, plus admin controls (numbers, templates, DB, thresholds). |
| **Competitor Agent** | A rival posing as a buyer. | External. Flagged automatically; agent is warned. |
| **System (backend)** | The automated brain. | Runs webhooks, AI, detection, routing, CRM sync — no human. |

**Role principle — least access:** an agent can never see another agent's leads or the
whole company pipeline. Every widening of access (team → all) is a deliberate role step.

---

## 4. High-Level Architecture (The Layers)

The system is 6 conceptual layers. Each becomes its own detailed doc.

1. **WhatsApp Layer** — Meta Cloud API: send, receive, templates, media, status, multi-number.
2. **Backend Layer** — Node.js/Express brain: webhook, routing, detection, AI calls, CRM sync, realtime, auth.
3. **Data Layer** — PostgreSQL (structured) + media storage (files) + competitor-number index.
4. **Intelligence Layer** — OpenAI scoring + duplicate detection + competitor detection + quality flags.
5. **CRM Layer** — Bitrix24 two-way sync via REST + n8n glue.
6. **Frontend Layer** — Web app (agent workspace + manager dashboard), real-time, media.

### Data flow — incoming message
1. Customer sends a WhatsApp message to one of the company numbers.
2. Meta calls our **webhook** (POST). Backend **verifies the signature** (`X-Hub-Signature-256`).
3. Backend saves the message, resolves **which number/agent** it belongs to.
4. Detection pipeline runs: competitor-agent check → duplicate-client check → AI sentiment/score.
5. Backend **pushes** the message + flags to the assigned agent's web app and to the manager dashboard **in real time** (WebSocket).
6. Backend **upserts** the contact + chat into **Bitrix24**.

### Data flow — outgoing message
1. Agent types a reply (or taps a template) in the web app.
2. Web app sends it to the backend (never to Meta).
3. Backend checks the **24-hour window** for that customer: open → free-form; closed → approved template.
4. Backend picks the **correct sending number** and calls Meta's Cloud API.
5. Backend logs the outbound message, then updates DB, dashboard, and Bitrix24.
6. Later, Meta sends **status callbacks** (sent → delivered → read / failed); backend updates the message state live.

---

## 5. Concept Area — WhatsApp / Meta Cloud API Layer

**What it is:** the official pipe to WhatsApp. Everything customer-facing goes through here.

Key concepts the engineers must internalise:

- **Webhook verification (setup):** Meta sends a one-time GET with a `hub.challenge`; we echo it back to prove we own the endpoint.
- **Webhook signature (every request):** Meta signs each POST with `X-Hub-Signature-256`. We **must** verify it using the app secret, or anyone could inject fake messages. *(This was missing in the original spec — we add it.)*
- **Two message types:**
  - *Free-form (service)* — any content, **only inside the open 24h window**, free.
  - *Template* — pre-approved, needed to open/re-open outside the window, paid.
- **Template categories & cost:** Utility (cheapest, order/appointment/follow-up style) < Marketing (promotional) ; Authentication (OTP — not used here). **Utility templates sent *inside* an open service window are free** under current Meta pricing.
- **Media messages:** inbound media arrives as a **media ID** — backend must download it from Meta and store it; outbound media must be uploaded to Meta first, then referenced. Types: image, document (PDF), audio/voice, video.
- **Message status events:** Meta reports `sent`, `delivered`, `read`, `failed`. We subscribe to these and reflect ticks/failures in the UI. *(Also missing in original spec — we add it.)*
- **Quality rating & tiers (per number):** each number has a health rating and a daily new-conversation cap. Bad behaviour (blocks/reports) drops the rating and can **ban** the number.
- **Token security:** the permanent System User token lives **only** on the backend as a secret/env var — never in the web app or CRM. Rotate immediately if leaked.

→ Detailed doc: **`10-whatsapp-cloud-api.md`**

---

## 6. Concept Area — Multi-Number Management

*(New vs original spec — the spec assumed a single company number.)*

**What it is:** we operate **several** WhatsApp numbers (e.g. per team, community, or agent).
The backend must know, for every message, *which number* it came in on and *which number*
to reply from.

Key concepts:
- **Number registry:** a `whatsapp_numbers` table maps each Phone Number ID → label, assigned team/agent, status, and live quality/health.
- **Inbound routing:** an incoming message is tied to the number it hit, then to the agent that number belongs to (or to the customer's existing assigned agent).
- **Outbound number selection:** replies go out from the **same number** the customer already talks to (never switch mid-conversation — it confuses customers and hurts trust).
- **Per-number health:** each number tracks its own quality rating, messaging tier, and daily usage. The dashboard shows Green/Yellow/Red per number; **Red auto-pauses** that number's cold outreach.
- **Load distribution:** having many numbers spreads outreach volume, but every number is warmed and monitored **independently**.

→ Detailed doc: **`11-multi-number-management.md`**

---

## 7. Concept Area — 24-Hour Window & Templates

**What it is:** the single most important concept for daily use and for cost.

- When a customer messages us, a **24h service window** opens → we reply free-form, free.
- After 24h of customer silence, the window **closes** → we can only reach them with an **approved template** (paid).
- A7 reality: customers go quiet for 2–3 days while the team finds a property, then the agent must re-open the chat. This must be **one action** in the UI.

System behaviour:
- Backend tracks `last_inbound_at` per customer → computes window open/closed.
- Web app shows a clear status: **green "Open — reply freely"** vs **grey "Closed — send a template"**.
- When closed, the free-text box is disabled and a **template menu** is shown — the agent physically cannot get stuck.
- Template menu is **pre-filled with the customer's name** and sends in one click.

**Starting template set** (to pre-approve in Meta):

| Template | Purpose | Category |
|----------|---------|----------|
| `welcome_intro` | First contact / greeting a new lead | Utility (or Marketing if promotional) |
| `property_ready` | "We found properties matching your needs" (re-open) | Utility |
| `follow_up` | Gentle follow-up after silence | Utility |
| `viewing_confirm` | Confirm a viewing date/time | Utility |
| `document_request` | Ask for documents (Emirates ID, etc.) | Utility |

- Each template can have **2–3 worded variants** — for *variety* (not a compliance guarantee; quality rating is what Meta actually judges).
- **Template lifecycle:** draft → submit to Meta → approved/rejected (allow 1–2 days). We need a fallback plan if a template is rejected or paused.

→ Detailed doc: **`12-window-and-templates.md`**

---

## 8. Concept Area — Opt-in / Consent & Ban-Safety

*(Critical — because we do **cold** outreach to new leads. This is the #1 future risk.)*

**Why it matters:** messaging brand-new leads who never opted in can trigger blocks/reports,
drop a number's quality rating, and get the number **banned**. Bans kill the business, so
safety is built into the system, not bolted on.

Concepts:
- **Consent record:** every customer has an opt-in state + source (e.g. "enquiry on Property Finder", "web form"). Stored in DB; written to Bitrix24.
- **First-contact rule:** cold first messages use **approved templates only**, and where possible carry a consent/greeting line and an easy opt-out.
- **Number warm-up:** a new number does not blast on day 1 — outreach volume ramps with the Meta messaging tier (250 → 1K → 10K → unlimited).
- **Per-number quality monitor:** dashboard shows each number's rating; **Red = auto-pause** outreach on that number.
- **Rate limiting:** caps on new conversations per number per hour/day.
- **Block/report tracking:** watch failed/blocked sends and back off automatically.

→ Detailed doc: **`13-consent-and-ban-safety.md`**

---

## 9. Concept Area — Backend Server (The Brain)

**Tech:** Node.js + Express (REST) + Socket.IO (realtime). It is the only component that
holds secrets and talks to Meta, OpenAI, and Bitrix24.

Conceptual modules:
- **Webhook handler** — verify signature, parse inbound messages + status events, enqueue work.
- **Message service** — persist messages, resolve customer/agent/number, manage the 24h window.
- **Number router** — pick inbound/outbound number (see §6).
- **Template service** — list approved templates, fill variables, send.
- **Detection pipeline** — competitor check → duplicate check → AI scoring (see §12–14).
- **AI service** — call OpenAI, parse JSON scores, store, alert on hot leads (§12).
- **Bitrix sync service** — upsert contacts/deals/timeline + custom fields, via REST/n8n (§15).
- **Realtime gateway** — Socket.IO rooms (per agent, per manager/team) push live updates.
- **Auth service** — web login (JWT), roles (agent/manager/admin), least-access enforcement.
- **Admin service** — manage numbers, templates, competitor DB, thresholds, re-assignment.
- **Media service** — download inbound / upload outbound media, storage abstraction (§11 data).
- **Worker/queue** — background jobs (AI scoring, Bitrix sync, media download) so webhooks stay fast.
- **Audit log** — every action (send, reassign, template, login) recorded with actor + time.

→ Detailed doc: **`20-backend-architecture.md`** (+ per-module sub-docs as needed)

---

## 10. Concept Area — Real-Time Web Delivery

**What it is:** how the dashboard and agent workspace update instantly, without refresh.

- **Transport:** WebSocket via **Socket.IO** (fallback to long-polling).
- **Rooms:** each agent joins their own room; managers join team rooms; admin joins an all-room.
- **Events pushed:** `message:new`, `message:status`, `lead:scored`, `alert:duplicate`, `alert:competitor`, `number:health`.
- **Optimistic UI:** the sender sees their message instantly; the real WhatsApp status (sent/delivered/read) updates the same bubble as callbacks arrive.

→ Covered inside **`20-backend-architecture.md`** and **`40-frontend-web-app.md`**

---

## 11. Concept Area — Data Layer (Database + Media + Competitor Index)

**PostgreSQL** for structured data; **file storage** for media; an **indexed table** for the
competitor number list. Conceptual tables (final schema goes in the detailed doc):

- `agents` — id, name, phone (login only), role, team/community, active.
- `whatsapp_numbers` — id, phone_number_id, label, assigned team/agent, quality rating, tier, status. *(new)*
- `customers` — id, wa_number (E.164), name, assigned_agent_id, assigned_number_id, bitrix_contact_id, sentiment_score, lead_status, is_competitor_agent, duplicate_flag, **consent_state, consent_source**, last_inbound_at. *(consent + number added)*
- `messages` — id, customer_id, agent_id (null if inbound), number_id, direction, body, **media_url, media_type**, is_template, template_name, wa_message_id, **status (sent/delivered/read/failed)**, created_at. *(media + status added)*
- `templates` — id, name, versions (jsonb), category, meta_status.
- `competitor_agents` — id, phone (indexed), source, added_at.
- `consents` / opt-in log — customer, state, source, timestamp. *(new)*
- `audit_log` — actor, action, target, timestamp, metadata. *(new — spec claimed audit but had no table)*
- `alerts` — type (hot/duplicate/competitor/behaviour), payload, seen, created_at.

**Media storage concept:** files never live in the DB — only their URL/key does. A **storage
driver** abstraction lets us keep files on the host VPS disk today and switch to S3 /
Cloudflare R2 later without code changes.

→ Detailed doc: **`30-database-schema.md`**

---

## 12. Concept Area — AI Intelligence (OpenAI)

**What it is:** the backend sends recent conversation text to **OpenAI** and gets back a
structured judgement so agents/managers focus where it matters.

- **Signals returned (JSON only):**
  - *Sentiment* — positive / neutral / negative.
  - *Seriousness score* — 0–100, real buyer vs time-waster.
  - *Lead status* — Hot / Warm / Cold (derived from score + thresholds).
  - *Intent* — buying / renting / browsing / **competitor fishing**.
  - *Behaviour flags* — rude / unprofessional / off-policy agent messages (quality monitoring).
- **When it runs (cost control):** not on every word — **batched** after a customer reply or every 3–4 messages.
- **Hot-lead alert:** if the score crosses the admin threshold → instant manager alert ("Serious customer — Agent X, Community Y").
- **Prompt design:** a fixed system instruction forces strict JSON output; parsing is validated and retried on mismatch.
- **Privacy note:** customer chat text leaves to OpenAI — must be handled per PDPL (consent + retention). Detailed doc covers what is/ isn't sent and redaction options.

→ Detailed doc: **`50-ai-intelligence.md`**

---

## 13. Concept Area — Duplicate-Client Detection

**Problem:** one customer contacts two/three A7 agents; they compete, undercut, deal breaks.

**Logic:**
1. Every incoming customer number is checked against all **currently active** conversations (active = within a configurable recent window).
2. If the same number is already open with a **different** agent → raise a **Duplicate-Client alert**.
3. Alert goes to both agents' manager(s) + the dashboard: *"Client +9715XXXX is talking to Agent A and Agent B."*
4. Management decides who keeps the client; the system can **re-assign** the chat to one agent (audited).

→ Detailed doc: **`51-duplicate-detection.md`**

---

## 14. Concept Area — Competitor-Agent Detection

**Problem:** many "buyers" on Property Finder/Bayut are rival agents fishing for owner
details to cut A7 out of the commission. A7 has a database of **30,000–100,000** agent
numbers.

**Logic:**
1. The number database is loaded into a **dedicated, indexed** table for fast lookup.
2. The moment any WhatsApp/call arrives, the number is checked **before the agent even replies**.
3. On match → app + dashboard show a clear banner: **"THIS IS A COMPETITOR AGENT."**
4. The agent adjusts approach — shares less, protects owner details, follows company policy.

**Keeping the list fresh:** admin bulk-uploads (Excel/CSV); can whitelist/remove a false
positive; optional AI assist can *suggest* new numbers when a caller behaves like an agent
(kept **manual-review by default** to avoid flagging real buyers).

**Compliance:** used **defensively** only (to recognise who is calling us) — never for
unsolicited cold marketing. Must follow UAE **PDPL** and **TDRA** rules.

→ Detailed doc: **`52-competitor-detection.md`**

---

## 15. Concept Area — Bitrix24 CRM Sync

**Principle:** Bitrix24 stays the **record of truth**. Agents never enter data twice — the
backend keeps Bitrix updated automatically.

**What syncs:**
- **Contacts** — every new customer creates/updates a Bitrix Contact.
- **Chat history** — conversations attached to the contact (timeline / linked deal).
- **Flags & scores** — sentiment score, lead status, competitor flag, duplicate flag → **custom fields**.
- **Deals** — serious leads can auto-create or move a Deal in the pipeline.

**How it connects:**
- Bitrix24 **REST API (inbound webhook)** on A7's on-prem Bitrix.
- **n8n** handles much of the glue: backend fires an event → n8n workflow → Bitrix action. Keeps heavy CRM logic out of core code, easy to change later.
- **Two-way:** changes in Bitrix (e.g. reassignment, deal stage) can flow back to the system where relevant.

**Custom fields to add in Bitrix:** Sentiment Score, Lead Status (Hot/Warm/Cold),
Is Competitor Agent (Y/N), Duplicate Alert (Y/N), Assigned Agent, Assigned Number,
Last WhatsApp Contact, Consent State.

→ Detailed doc: **`60-bitrix24-sync.md`**

---

## 16. Concept Area — Frontend Web App

**One web app, two experiences by role**, real-time, media-capable, no page refresh.

### 16.1 Agent Workspace
- **Login** — company credentials (JWT). No WhatsApp key in the browser.
- **Chat list** — only this agent's assigned customers, newest first, unread badges, flags (🔴 serious / ⚠️ competitor / 👥 duplicate).
- **Chat window** — full conversation, send text + media, live status ticks; shows window **open/closed** state.
- **Template menu** — when window closed, one-click approved templates, pre-filled with name.
- **Customer card** — name, community interest, budget, Bitrix link, and any auto-flags.
- **Notifications** — in-browser real-time alerts for new customer messages.

### 16.2 Manager / Admin Dashboard
- **Live chats** — every agent's conversations updating in real time.
- **Hot leads** panel — all serious customers right now, across agents.
- **Alerts feed** — competitor detected, duplicate detected, agent misbehaviour.
- **Agent scoreboard** — messages sent, response time, hot leads handled, deals moved.
- **Number health** — per-number quality (Green/Yellow/Red), tier, usage; pause/resume outreach.
- **Search** — any customer/number → full history instantly.
- **Admin controls** — add/remove agents & assign communities; manage numbers; add/edit templates; upload competitor DB; set hot-lead threshold; re-assign a customer in one click; export conversations/reports.

**Tech:** React + Tailwind, Socket.IO client for realtime, role-based routing/guards.

→ Detailed doc: **`40-frontend-web-app.md`**

---

## 17. Concept Area — Cost Control (Meta Pricing)

- **Free window:** customer messages + our replies inside the 24h window are effectively free.
- **Per-message pricing (current model):** Meta moved to charging **per delivered template message** by category; **Utility templates inside an open window are free**. Exact UAE rates must be confirmed in Meta Business Manager before go-live.
- **Optimisation logic:** always prefer free-form inside the open window; when a template is needed, default to **Utility** over Marketing where it qualifies.
- **Reporting:** monthly manager report — free messages vs paid templates, per number, estimated spend.

→ Detailed doc: **`53-cost-control.md`**

---

## 18. Concept Area — Security & Compliance

- **Token isolation** — all secrets (WhatsApp token, Bitrix webhook, OpenAI key) live only as backend env vars.
- **Webhook signature verification** — reject any unsigned/forged Meta callback.
- **Auth & roles** — JWT, least-access, agents scoped to their own chats.
- **Audit trail** — every action logged with actor + time.
- **Encryption** — HTTPS in transit; sensitive fields/media protected at rest.
- **Compliance** — UAE **PDPL** (personal data) + **TDRA** (telemarketing); competitor DB used defensively only; opt-in for outreach; a defined **data-retention** policy.
- **Rate limiting** — protect endpoints and per-number sending.

→ Detailed doc: **`70-security-and-compliance.md`**

---

## 19. Concept Area — Deployment & Infrastructure

- **Hosting** — backend on the project server (**AWS or Hostinger VPS**), HTTPS, own domain.
- **Components to run** — Node backend, PostgreSQL, media storage, n8n, (optional) worker process.
- **Secrets** — environment variables, never in code.
- **Meta setup** — register production webhook URL, get templates approved, configure numbers.
- **Data loads** — import competitor DB, create agent accounts, assign communities.
- **Rollout** — pilot with 3–5 agents for a week → then mandate company-wide.
- **Backups & monitoring** — DB + media backups, uptime + error monitoring, per-number quality alerts.

→ Detailed doc: **`80-deployment-and-infra.md`**

---

## 20. Documentation Roadmap (What We Build Next)

Each concept above becomes one detailed technical doc. Proposed set & order:

| # | Doc file | Area | Priority |
|---|----------|------|----------|
| 10 | `10-whatsapp-cloud-api.md` | WhatsApp send/receive/templates/media/status/signature | ⭐ Core |
| 11 | `11-multi-number-management.md` | Number registry, routing, per-number health | ⭐ Core |
| 12 | `12-window-and-templates.md` | 24h window + template lifecycle | ⭐ Core |
| 13 | `13-consent-and-ban-safety.md` | Opt-in, warm-up, quality monitoring | ⭐ Core |
| 20 | `20-backend-architecture.md` | Modules, queues, realtime, APIs | ⭐ Core |
| 30 | `30-database-schema.md` | Full PostgreSQL schema + ERD | ⭐ Core |
| 40 | `40-frontend-web-app.md` | Agent workspace + manager dashboard, components, screens | ⭐ Core |
| 50 | `50-ai-intelligence.md` | OpenAI prompts, scoring, alerts | Phase 2 |
| 51 | `51-duplicate-detection.md` | Duplicate-client logic | Phase 2 |
| 52 | `52-competitor-detection.md` | Competitor DB + lookup | Phase 2 |
| 53 | `53-cost-control.md` | Pricing + reporting | Phase 2 |
| 60 | `60-bitrix24-sync.md` | CRM two-way sync + n8n + custom fields | Phase 2 |
| 70 | `70-security-and-compliance.md` | Security + PDPL/TDRA | Cross-cutting |
| 80 | `80-deployment-and-infra.md` | Hosting, go-live, backups | Final |

**Build order principle (from the spec, still valid):** ship the daily-use core first —
WhatsApp + multi-number + 24h window + agent web app + backend + DB — then layer
intelligence (AI, detection), then CRM, then polish and deploy.

---

*End of Master Concept Document. Next step: pick a detailed doc from the roadmap above and
we write it in full (data contracts, endpoints, screens, edge cases).*
