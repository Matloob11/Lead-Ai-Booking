# Doc 90 — wacrm ↔ A7 Gap Analysis & Modification Plan

> Decision: **do not build from scratch — fork `wacrm` and adapt it.** This doc maps every
> A7 requirement (Docs 10–80) to what wacrm already ships, and gives an exact modification
> plan for each gap.
> Base repo: `wacrm-main/` · Stack: Next.js 16 + Supabase (Postgres + Auth + Storage + RLS +
> Realtime) + official Meta Cloud API · License: MIT (fork/rebrand/self-host allowed).

---

## 0. Verdict

wacrm covers roughly **70–80%** of A7's system out of the box, production-grade and tested.
The remaining 20–30% is **A7-specific** (multi-number, competitor/duplicate detection, lead
scoring, consent/ban-safety, Bitrix sync). All of it is **additive** to a clean, typed
codebase — far cheaper than greenfield.

**Coverage legend:** ✅ ready · ⚠️ partial (adapt/extend) · ❌ build (A7-specific)

---

## 1. Requirement → wacrm coverage (master map)

| Doc | Area | wacrm | Notes |
|-----|------|:----:|-------|
| 10 | WhatsApp Cloud API | ✅ | Webhook GET verify + POST **HMAC signature verify**, send, media proxy, template submit + template-status webhook, message-status ladder. All present & tested. |
| 11 | Multi-number | ❌ | **Single number per account by design** (`whatsapp_config UNIQUE(account_id)`). Biggest change → **Doc 91**. |
| 12 | 24h window & templates | ⚠️ | Templates: ✅ full (categories, Meta approval, lifecycle). Window gating: ❌ not enforced in app (no open/closed UI, no auto-switch to template). Add window logic. |
| 13 | Consent & ban-safety | ❌ | No consent state, warm-up, or per-number quality auto-pause. Template-quality webhook exists to build on. |
| 20 | Backend architecture | ⚠️ | Different stack (Next.js API routes + Supabase + `after()`/cron, **not** Express + Socket.IO + BullMQ). **Better** for a web app. Revise Doc 20 to match. |
| 30 | Database schema | ⚠️ | Account-scoped schema covers contacts/convos/messages/templates/broadcasts/deals. A7 tables missing: competitor_agents, consents, ai_scores, message_costs, audit_log, multi-number fields. Additive migrations. |
| 40 | Frontend web app | ✅ | Inbox, dashboard, contacts, pipelines, broadcasts, automations, flows, settings, team/roles. Add A7 panels (banners, number health, lead score). |
| 50 | AI intelligence (OpenAI) | ⚠️ | AI infra ✅ (OpenAI/Anthropic providers, context, usage, knowledge base). But it does **reply drafting/auto-reply**, not **lead scoring/sentiment/intent**. Add a scoring feature reusing the provider. |
| 51 | Duplicate-client detection | ❌ | wacrm de-dupes contacts/convos (opposite intent). Need cross-agent/number "same client, 2 agents" alert. |
| 52 | Competitor-agent detection | ❌ | No competitor DB / lookup / banner. A7-specific. |
| 53 | Cost control | ❌ | No message cost tagging/report. Additive. |
| 60 | Bitrix24 sync | ❌ | Not built-in. But **outbound webhooks + public REST API + MCP** make it integrable via n8n. |
| 70 | Security & compliance | ✅ | AES-256-GCM token encryption, RLS everywhere, HMAC webhooks (in+out), SSRF guard, rate limiting, hashed API keys. Add PDPL/TDRA retention + audit + consent. |
| 80 | Deployment & infra | ✅ | Hostinger-native + Supabase. Revise Doc 80 for Supabase instead of self-managed Postgres. |

---

## 2. What wacrm gives us for FREE (already built)

- **WhatsApp layer** — verified webhook (GET + signed POST), send text/media/template, media
  download+proxy, message status ladder (sent→delivered→read→replied, failed side-branch),
  reactions, swipe-reply context, interactive button/list replies.
- **Templates** — create/edit, submit to Meta (incl. image-header resumable upload), track
  approval/quality via template webhook, dry-run mode for dev.
- **Broadcasts** — audience filter, per-recipient variables, delivery/read/reply counts.
- **Shared inbox** — conversations with status + assignment + unread, realtime updates.
- **Contacts** — dedupe (phone-suffix match), tags, custom fields, notes, CSV import.
- **Pipelines/deals** — Kanban, deals linked to conversations.
- **Automations** (no-code) — triggers (new message, keyword, new/first contact, interactive,
  schedule), conditions, actions, cron engine.
- **Flows** — visual bot builder (interactive menus, per-contact runs).
- **AI** — OpenAI/Anthropic providers, draft reply, auto-reply bot with human handoff + cap,
  knowledge base (Postgres full-text + optional pgvector), usage log, playground. BYO key,
  encrypted.
- **Teams** — accounts, invite links, roles (owner/admin/agent/viewer), RLS-enforced scope,
  ownership transfer, member presence.
- **Platform** — public REST API `/api/v1` + scoped API keys, MCP server, outbound webhooks
  (signed, SSRF-guarded), notifications, i18n, rate limiting, dashboard analytics.

That inventory alone is most of Docs 10, 40, 70, 80 and the AI plumbing of 50.

---

## 3. Per-gap modification plans

### GAP 1 — Multi-number (Doc 11) ❌ → **highest priority**
- **What:** allow many WhatsApp numbers per account; pin each conversation to a number.
- **Change:** drop `whatsapp_config_account_id_key`; add `whatsapp_config_id` to
  `conversations`; number-aware webhook + send; number list UI.
- **Full plan:** **[Doc 91 — Multi-number modification](91-multi-number-modification.md).**
- **Effort:** Medium (the biggest single change; webhook already routes by `phone_number_id`,
  so half the work is done).

### GAP 2 — 24h window enforcement (Doc 12) ⚠️
- **What:** compute window open/closed per conversation from last **inbound** time; when
  closed, disable free-text and force an approved template.
- **Change:**
  - DB: no new table needed — derive from `messages` (latest inbound `created_at`) or add
    `conversations.last_inbound_at` (cheap, updated in webhook `processMessage`).
  - Backend: in `send-message.ts`, if window closed and payload is free-form → reject with a
    typed error (`window_closed`); allow templates always.
  - Frontend (`inbox`): show 🟢/⚪ banner; when closed, disable composer + open the template
    picker (template UI already exists).
- **Effort:** Small–Medium. Reuses existing template send.

### GAP 3 — Consent & ban-safety (Doc 13) ❌
- **What:** consent state per contact, cold-outreach gating, number warm-up, per-number
  quality auto-pause.
- **Change:**
  - DB: add `contacts.consent_state / consent_source / consent_at / opt_out_at`; add health
    fields on `whatsapp_config` (quality_rating, messaging_tier, warmup_stage, status) — folded
    into Doc 91's migration.
  - Backend: outreach/broadcast send checks consent + number status before sending; STOP
    keyword → `opted_out`; template-quality webhook (already received) flips a number to Red →
    pause outreach.
  - Frontend: consent shown on contact + number-health panel with pause/resume.
- **Effort:** Medium. Broadcast + template-webhook infra already exists to hook into.

### GAP 4 — Lead scoring / sentiment / intent (Doc 50) ⚠️
- **What:** score each conversation (sentiment, seriousness 0–100, lead status, intent,
  behaviour flag) using OpenAI.
- **Change:**
  - DB: add `ai_scores` table + latest-score fields on `contacts` (or a `lead_state` table).
  - Backend: new `src/lib/ai/scoring.ts` reusing `src/lib/ai/providers/openai.ts` +
    `context.ts`; trigger it from the webhook (batched, on inbound) like `dispatchInboundToAiReply`
    already does — same pattern, new consumer. Fire `hot_lead` notification on threshold.
  - Frontend: AI panel in the inbox contact card + a "Hot Leads" dashboard panel.
- **Effort:** Small–Medium. The AI provider, context builder, usage tracking, and inbound
  dispatch hook **already exist** — this is a new consumer, not new plumbing.

### GAP 5 — Duplicate-client detection (Doc 51) ❌
- **What:** same customer active with 2 agents/numbers → alert + one-click reassign.
- **Change:**
  - With multi-number (Doc 91), a customer messaging two numbers = two conversations. Detect:
    on inbound, if the same contact has active conversations under >1 `assigned_agent_id`
    (or >1 number) → raise a `duplicate` notification + set a flag on the contact.
  - Backend: add check in `processMessage` (after conversation resolve).
  - Frontend: amber banner in inbox + alert in dashboard + reassign action (assignment already
    exists on conversations).
- **Effort:** Small–Medium (leans on existing assignment + notifications).

### GAP 6 — Competitor-agent detection (Doc 52) ❌
- **What:** 30k–100k number DB; check every inbound before reply; red banner.
- **Change:**
  - DB: add `competitor_agents(phone UNIQUE indexed, source, whitelisted, added_at)` + CSV bulk import.
  - Backend: in webhook `processMessage`, one indexed lookup on sender phone → set
    `contacts.is_competitor_agent` + `competitor` notification. (Optional: AI intent
    `competitor_fishing` as a soft signal — reuse Gap 4 scoring.)
  - Frontend: red banner in inbox; admin CSV upload + whitelist screen.
- **Effort:** Small–Medium. Self-contained; fast even at 100k rows.

### GAP 7 — Cost control (Doc 53) ❌
- **What:** tag each outbound with category (service/utility/marketing) + estimated cost; monthly report.
- **Change:**
  - DB: `message_costs` table (or columns on messages).
  - Backend: tag at send time in `send-message.ts` / broadcast core using template category + window state.
  - Frontend: cost report in dashboard/admin.
- **Effort:** Small. Additive, no core change.

### GAP 8 — Bitrix24 two-way sync (Doc 60) ❌
- **What:** mirror contacts/deals/timeline + custom fields to Bitrix; optional back-sync.
- **Change (recommended, low-code):**
  - Use wacrm's **outbound webhooks** (`webhook_endpoints`, events like `message.received`,
    `conversation.created`, `message.status_updated`) → **n8n** workflows → Bitrix REST.
  - Use the **public API** `/api/v1` for reads and the **MCP server** where useful.
  - Add a Bitrix inbound endpoint (`/api/webhook/bitrix`) for back-sync (reassignment, deal stage).
  - Add A7 fields (lead score, competitor/duplicate flags) to the webhook payloads.
- **Effort:** Medium, but mostly **outside** the app (n8n) — minimal core code.

### GAP 9 — Audit log + retention (Doc 70) ⚠️
- **What:** general append-only audit + PDPL retention/purge + consent records.
- **Change:** add `audit_log` table (wacrm has `automation_logs`/`ai_usage_log` but not a
  general one); write on send/reassign/import/settings/export; scheduled purge job (via the
  existing cron pattern); consent covered in Gap 3.
- **Effort:** Small.

---

## 4. Docs that need REVISION (stack alignment)

Because wacrm's stack differs from the greenfield assumption, revise (not rewrite) these:

- **Doc 20 (Backend):** Express+Socket.IO+BullMQ → **Next.js API routes + Supabase Realtime +
  `after()`/cron**. Concepts (webhook, detection pipeline, RBAC) stay; mechanisms change.
- **Doc 30 (DB):** align to wacrm's account-scoped schema; A7 tables become **additive migrations**
  (037+), not a fresh schema.
- **Doc 80 (Deploy):** Supabase-managed Postgres/Auth/Storage + Hostinger Node — drop the
  self-managed Postgres/Redis assumptions.

The other docs (10, 40, 50, 70) stay valid as **feature specs**; wacrm implements most and we
extend the rest.

---

## 5. Recommended build order (on top of the fork)

1. **Fork + run locally** ([Doc 92](92-local-setup-guide.md)) — get the base working with Supabase + Meta.
2. **Multi-number** ([Doc 91](91-multi-number-modification.md)) — unblocks A7's core model.
3. **24h window gating** (Gap 2) — daily-use correctness + cost.
4. **Competitor + duplicate detection** (Gaps 5,6) — high business value, self-contained.
5. **Lead scoring + hot-lead alerts** (Gap 4) — reuse AI infra.
6. **Consent + ban-safety** (Gap 3) — before heavy cold outreach.
7. **Cost control + audit/retention** (Gaps 7,9).
8. **Bitrix24 via n8n** (Gap 8).
9. **Rebrand** (navy & gold, A7 logo) + pilot.

---

## 6. Effort summary

| Gap | Effort | Blast radius |
|-----|--------|--------------|
| Multi-number | Medium | schema + webhook + send + UI |
| 24h window | Small–Med | send + inbox UI |
| Consent/ban-safety | Medium | broadcast + config + UI |
| Lead scoring | Small–Med | new AI consumer + UI |
| Duplicate detection | Small–Med | webhook + notifications + UI |
| Competitor detection | Small–Med | new table + webhook + UI |
| Cost control | Small | send tagging + report |
| Bitrix sync | Medium | mostly n8n, little core |
| Audit/retention | Small | new table + cron |

**Net:** one clear medium change (multi-number) + several small/self-contained additions, all
on a tested base. This is weeks, not months.

---

*Next: [Doc 91 — Multi-number modification](91-multi-number-modification.md) · [Doc 92 — Local setup](92-local-setup-guide.md).*
