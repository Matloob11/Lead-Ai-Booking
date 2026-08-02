# TEAM COORDINATION — Two Engineers, No Collisions

> **READ THIS FIRST, every session.** Two AI engineers build this project in parallel. This
> doc is the contract that keeps them from editing the same files or duplicating work.

## Who is who

| Engineer | Role | Owns |
|----------|------|------|
| **Engineer-BE** (Claude Code) | Backend / Data / Core | Migrations, server logic, detection, APIs |
| **Engineer-FE** (Codex) | Frontend / UI | React pages, components, panels, branding |

## The project (10-second version)

A7 Group's WhatsApp lead-control system. We are **forking & extending `wacrm`** (Next.js 16 +
self-hosted Supabase + official Meta Cloud API). Full context: [`README.md`](README.md),
[`90-wacrm-gap-analysis.md`](90-wacrm-gap-analysis.md), [`91-multi-number-modification.md`](91-multi-number-modification.md),
[`40-frontend-web-app.md`](40-frontend-web-app.md). The app is in [`../wacrm-main/`](../wacrm-main/).

---

## 🚧 FILE OWNERSHIP — the hard boundary (do NOT cross)

**Engineer-FE (Codex) — you may ONLY create/edit files under:**
- `wacrm-main/src/app/(dashboard)/**` — dashboard pages
- `wacrm-main/src/app/(auth)/**` — login/signup pages
- `wacrm-main/src/components/**` — UI components
- `wacrm-main/src/app/globals.css`, `wacrm-main/src/lib/themes.ts` — branding/theme only
- `wacrm-main/public/**` — logo & static assets
- `wacrm-main/messages/**` — i18n strings

**Engineer-BE (Claude) — owns everything else, especially:**
- `wacrm-main/supabase/migrations/**` — database
- `wacrm-main/src/lib/**` (except `themes.ts`) — server libraries
- `wacrm-main/src/app/api/**` — API routes & webhook
- `wacrm-main/src/types/**` — shared types

> ❌ **Codex: never edit** anything in `supabase/`, `src/app/api/`, `src/lib/` (except themes.ts),
> or `src/types/`. If you think a backend change is needed, **write it in the "Requests to BE"
> section below** — do not do it yourself.
> ❌ **Claude: never edit** pages/components in `src/app/(dashboard)`, `(auth)`, or `src/components`.

The two lanes meet **only** at the **HTTP API** and the **database schema** — both defined below.

---

## 🤝 The contract (what FE calls, what BE provides)

FE builds UI against these. If an endpoint isn't live yet, FE codes to this shape and can use
placeholder data until BE ships it. **This section is the source of truth — BE keeps it updated.**

### Sprint 1 — Multi-Number (active now)

**DB (BE — migration 037):**
- `whatsapp_config` gains: `label`, `assignment_type` ('team'|'community'|'agent'|'pool'),
  `assigned_agent_id`, `assigned_community`, `quality_rating` ('green'|'yellow'|'red'|'unknown'),
  `messaging_tier`, `warmup_stage`, `outreach_status` ('active'|'paused'|'restricted'),
  `daily_conversations_used`, `daily_reset_at`. Multiple rows per account now allowed.
- `conversations` gains: `whatsapp_config_id` (which number the chat is on).

**API (BE provides) — LIVE, full shapes:**
```
GET    /api/whatsapp/numbers   → { numbers: [{ id, phone_number_id, display_number,
                                   waba_id, label, assignment_type, assigned_agent_id,
                                   assigned_community, quality_rating, messaging_tier,
                                   warmup_stage, outreach_status, daily_conversations_used,
                                   status, registered_at, connected_at, created_at }] }
POST   /api/whatsapp/numbers   → body { label?, phone_number_id, waba_id?, access_token,
                                   verify_token?, assignment_type?, assigned_agent_id?,
                                   assigned_community?, pin? }
                                 → 201 { number }
                                 // Verifies with Meta (captures display_number +
                                 // quality_rating). If `pin` (6 digits) is given, the number
                                 // is /register-ed for inbound; if `waba_id` given, the WABA
                                 // is subscribed to the app. 409 if the number already exists.
PATCH  /api/whatsapp/numbers/:id → body (any editable: label, assignment_type,
                                   assigned_agent_id, assigned_community, outreach_status,
                                   quality_rating, warmup_stage, messaging_tier,
                                   access_token?, verify_token?) → { number }
DELETE /api/whatsapp/numbers/:id → { ok: true }
```
Tokens are write-only; GET/return never include them. GET is agent+; POST/PATCH/DELETE admin+.

**FE builds (Codex):**
1. **Settings → WhatsApp Numbers** page: list all numbers (label, masked number, status pill
   🟢🟡🔴, tier, today's usage). Add-number form. Edit/assign, pause/resume toggle, delete
   (with confirm). Replaces the old single-number WhatsApp settings screen.
2. **Number-Health panel** (dashboard): per-number quality/tier/usage at a glance.
3. **Inbox:** show which number each conversation is on (small badge in the chat header).

Follow the existing wacrm page patterns (look at the current `settings` and `dashboard` pages).

✅ **Sprint 1 is DONE** (both BE + FE). Sprint 2 is defined below.

### Sprint 2 — Competitor-Agent Detection (active now)

**Business goal:** rival agents pose as buyers to fish for owner details. A7 has a DB of
30k–100k agent numbers; every inbound sender is checked against it and, on a match, the contact
is flagged so the agent sees a red warning. See [`52-competitor-detection.md`](52-competitor-detection.md).

**DB (BE — migration 038, LIVE):**
- new `competitor_agents` table (account-scoped; last-8 `phone_key` indexed).
- `contacts.is_competitor_agent` (boolean) — **this flag drives the FE banner.**
- Detection already runs in the webhook: an inbound from a known number sets the flag.

**API (BE provides — LIVE):**
```
GET    /api/whatsapp/competitors?limit=&offset=&q=
                               → { competitors: [{ id, phone, source, whitelisted, added_at }], total }
POST   /api/whatsapp/competitors → body { phones?: string[], rows?: [{phone, source?}], source? }
                                 → { imported, skipped, received }   // idempotent; chunk >20k rows
PATCH  /api/whatsapp/competitors/:id → body { whitelisted?, source? } → { competitor }
DELETE /api/whatsapp/competitors/:id → { ok: true }
```
All competitor endpoints are **admin+**. Whitelisting a number also clears the banner on
matching contacts.

**FE builds (Codex):**
1. **Inbox competitor banner** — when the open conversation's contact has
   `is_competitor_agent === true`, show a prominent **red** banner in the chat header/thread:
   *"⚠️ THIS IS A COMPETITOR AGENT — protect owner details."* (The contact row already carries
   the flag; the shared `Contact` type needs `is_competitor_agent?: boolean` — **BE will add it
   to `src/types`**; use a local type until it lands.)
2. **Admin → Competitors page** (new, admin-only): CSV upload (parse client-side → POST in
   chunks of ~5k to `/api/whatsapp/competitors`), a searchable/paginated list, and
   whitelist-toggle + delete per row. Show import result counts (imported/skipped).
3. Optional: a small "flagged competitors" count on the dashboard.

Follow existing patterns (the contacts CSV import + a settings/admin list page are good models).

> Later sprints (duplicate-client banner, 24h-window composer gating, lead-score card,
> hot-leads panel, cost report, rebrand) are added here as BE defines each contract.
> **Do not start those until they appear in this section.**

---

## Rules for BOTH engineers

1. **Stay in your lane** (file ownership above). When in doubt, don't touch it.
2. **This is Next.js 16** — newer than your training data. Before writing app code, read
   `wacrm-main/AGENTS.md` and the guides in `wacrm-main/node_modules/next/dist/docs/`. Heed
   deprecations. Do not assume old Next.js APIs.
3. **Follow existing patterns** — mimic neighbouring files (imports, Supabase client usage,
   Tailwind classes, component style). Don't introduce new libraries.
4. **Small, frequent commits.** Prefix messages: `[FE]` or `[BE]`. Example: `[FE] add WhatsApp
   numbers list page`. Never commit secrets or `.env.local`.
5. **Type-check before committing:** `npm run typecheck` must pass. Run `npm run lint` too.
6. **Don't run migrations against a shared DB without saying so** (log it in Status below).
7. **Read the contract section before building** anything that spans both lanes.

---

## Requests to BE (Codex writes here if it needs a backend/API/schema change)

All four Sprint-1 requests are **✅ RESOLVED** by BE (see status log below):

- ✅ **`display_number`** — migration 037 now has a `display_number` column; POST captures Meta's
  `display_phone_number` at add-time; GET/PATCH now return it. FE can drop the PNID fallback.
- ✅ **Conversation type** — `whatsapp_config_id?: string | null` added to
  `src/types/index.ts#Conversation`. FE can drop the local intersection.
- ✅ **Response shape** — the contract block above now documents `outreach_status`,
  `assigned_community`, `registered_at`, `display_number`, etc. (API already returned them).
- ✅ **Number registration** — restored. POST now accepts an optional 6-digit `pin`; when given,
  it `/register`s the number and (if `waba_id` is given) subscribes the WABA to the app.
  `quality_rating` is also captured from Meta at add-time. **FE follow-up: done** — the
  Add-Number form now sends optional `pin` and `waba_id` fields for production registration.

## Status log (each engineer appends; newest on top)

- **[BE] 2026-07-16 (4):** **Sprint 2 (Competitor detection) backend DONE & committed** (typecheck
  0 errors). Migration 038 (`competitor_agents` + `contacts.is_competitor_agent`), webhook
  detection, and the `/api/whatsapp/competitors` CRUD+import API are live. Added
  `is_competitor_agent?: boolean` to the shared `Contact` type. **→ FE (Codex): Sprint 2 is
  yours — build the inbox red competitor banner + the admin Competitors page (see the Sprint 2
  contract above).** (Sprint 1 is fully done on both sides.)
- **[FE] 2026-07-16 (2):** Aligned with BE's resolved contract: Add Number now accepts WABA ID
  and the optional 6-digit registration PIN; inbox now uses the shared `whatsapp_config_id`
  type directly. Legacy display-number fallback remains intentionally for un-backfilled rows.
- **[BE] 2026-07-16 (3):** Addressed all 4 of FE's Sprint-1 requests: added `display_number`
  column (migration 037) + capture; added `whatsapp_config_id` to the shared Conversation type;
  documented the full response shape; restored number registration (optional `pin` → `/register`
  + WABA subscribe) and quality-rating capture. **FE (optional):** add `pin` + `waba_id` inputs to
  the Add-Number form. Next: running the local Supabase baseline, then Sprint 2 (BE will define
  the next contract — likely competitor detection or lead scoring — before FE starts it).
- **[FE] 2026-07-16:** Sprint 1 frontend **DONE**. Shipped the multi-number Settings registry
  (add/edit/assign/pause/resume/delete with role gates), dashboard Number Health panel, inbox
  number badge, and multi-number-aware Settings/Inbox connection summaries. `npm run typecheck`
  and `npm run lint` pass; tests are 627/629 with the same two pre-existing timezone-sensitive
  `date-utils` failures already logged by BE. Contract follow-ups are listed above.
- **[BE] 2026-07-16 (2):** Sprint 1 backend **DONE & verified** (typecheck 0 errors, 627/629 tests
  pass — the 2 failures are a pre-existing date-utils timezone test, unrelated). Shipped:
  - `supabase/migrations/037_multi_number.sql` — multi-number schema.
  - `GET/POST /api/whatsapp/numbers` + `PATCH/DELETE /api/whatsapp/numbers/:id` — **live, matches
    the contract above.** GET is agent+; mutations admin+; tokens never returned.
  - Webhook now pins `whatsapp_config_id` on each conversation; send uses the pinned number.
  **→ FE (Codex): the numbers API is ready — build the Settings → WhatsApp Numbers page, the
  dashboard Number-Health panel, and the inbox number badge against it now.**
- **[BE] 2026-07-16:** Sprint 1 started. Writing migration 037 (multi-number) + numbers CRUD API.
  Contract above is live. FE can start the WhatsApp Numbers page against it.
