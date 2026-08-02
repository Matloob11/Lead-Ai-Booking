# Doc 91 — Multi-Number Modification Plan (wacrm)

> How to turn wacrm from **one WhatsApp number per account** into **many numbers per account**,
> with each conversation pinned to a number. This is the single biggest change needed for A7.
> Prereq reading: [Doc 90 gap analysis](90-wacrm-gap-analysis.md) · [Doc 11 concept](11-multi-number-management.md).

---

## 1. Current state (verified in code)

- **`whatsapp_config`** — one row per account, constrained by
  `whatsapp_config_account_id_key UNIQUE (account_id)` (migration 017) **and**
  `whatsapp_config_phone_number_id_key UNIQUE (phone_number_id)` (migration 013).
- **Webhook** (`src/app/api/whatsapp/webhook/route.ts`) already routes inbound by
  `metadata.phone_number_id` → looks up the config → derives `account_id`, `user_id`, token.
  **Number-first routing already exists.** ✅
- **Conversations** — unique on `(account_id, contact_id)`
  (`idx_conversations_account_contact`, migration 036). One conversation per contact per account.
- **Send** (`src/lib/whatsapp/send-message.ts`) loads the config by
  `.eq('account_id', accountId).single()` — assumes exactly one number per account.

**So the only things blocking multi-number are:** (a) the `UNIQUE(account_id)` constraint,
(b) conversations not knowing *which* number they belong to, and (c) send loading "the
account's" number instead of "the conversation's" number.

---

## 2. Design decisions

1. **Many `whatsapp_config` rows per account.** Keep `UNIQUE(phone_number_id)` (each number
   maps to exactly one config → webhook stays unambiguous). Drop `UNIQUE(account_id)`.
2. **Pin the number on the conversation.** Add `conversations.whatsapp_config_id`. Set it on
   first inbound (from the resolved config) and on first outbound (from the chosen number).
3. **Conversation identity becomes per-number.** Change uniqueness from `(account_id, contact_id)`
   to `(account_id, contact_id, whatsapp_config_id)`. Effect: a customer who messages **two
   different company numbers** gets **two conversations** — which is exactly A7's "same client,
   two desks" signal that feeds [duplicate detection](51-duplicate-detection.md). (If A7 later
   prefers one merged thread, revert to the 2-col unique — but per-number is the right default
   for the team/community model.)
4. **Outbound never switches number** mid-conversation — always use the pinned
   `whatsapp_config_id` ([Doc 11](11-multi-number-management.md) continuity rule).
5. **Greenfield = trivial backfill.** A7 starts fresh, so no production dedup pain; the
   migration still includes a safe backfill for completeness.

---

## 3. Schema change — new migration `037_multi_number.sql`

```sql
-- ============================================================
-- 037_multi_number.sql — many WhatsApp numbers per account
-- ============================================================

-- 1) Allow multiple numbers per account. Keep phone_number_id unique
--    (webhook routing depends on it). Drop the one-per-account rule.
ALTER TABLE whatsapp_config
  DROP CONSTRAINT IF EXISTS whatsapp_config_account_id_key;

-- 2) A7 multi-number + health/ban-safety fields (also serves Doc 13).
ALTER TABLE whatsapp_config
  ADD COLUMN IF NOT EXISTS label            TEXT,
  ADD COLUMN IF NOT EXISTS assignment_type  TEXT
      DEFAULT 'pool' CHECK (assignment_type IN ('team','community','agent','pool')),
  ADD COLUMN IF NOT EXISTS assigned_agent_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS assigned_community TEXT,
  ADD COLUMN IF NOT EXISTS quality_rating   TEXT
      DEFAULT 'unknown' CHECK (quality_rating IN ('green','yellow','red','unknown')),
  ADD COLUMN IF NOT EXISTS messaging_tier   TEXT DEFAULT 'tier_250',
  ADD COLUMN IF NOT EXISTS warmup_stage     TEXT
      DEFAULT 'new' CHECK (warmup_stage IN ('new','warming','established')),
  ADD COLUMN IF NOT EXISTS outreach_status  TEXT
      DEFAULT 'active' CHECK (outreach_status IN ('active','paused','restricted')),
  ADD COLUMN IF NOT EXISTS daily_conversations_used INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS daily_reset_at   TIMESTAMPTZ;

-- 3) Pin each conversation to the number it belongs to.
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS whatsapp_config_id UUID
      REFERENCES whatsapp_config(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_conversations_wa_config
  ON conversations(whatsapp_config_id);

-- 4) Backfill existing conversations to the account's (currently sole) number.
UPDATE conversations c
SET whatsapp_config_id = w.id
FROM whatsapp_config w
WHERE w.account_id = c.account_id
  AND c.whatsapp_config_id IS NULL;

-- 5) Swap conversation uniqueness: per-number now.
DROP INDEX IF EXISTS idx_conversations_account_contact;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_account_contact_number
  ON conversations (account_id, contact_id, whatsapp_config_id);

-- NOTE: Postgres treats NULLs as distinct in unique indexes, so pre-backfill
-- NULL rows won't collide. Ensure step 4 ran (it does above). For strictness
-- you may later set whatsapp_config_id NOT NULL once all rows are backfilled.
```

> Also update `merge_duplicate_conversations()` (migration 036) grouping if you re-run merges:
> group by `(account_id, contact_id, whatsapp_config_id)` instead of `(account_id, contact_id)`.
> For greenfield A7 this function has nothing to merge, so it's optional.

---

## 4. Code changes (exact files)

### 4.1 Webhook — pin the number on the conversation
**File:** `src/app/api/whatsapp/webhook/route.ts`

- `processMessage(...)` already receives the resolved `config`. Pass `config.id` through:
  - Change `processMessage(message, contact, config.account_id, config.user_id, token)` →
    add `config.id` (call it `whatsappConfigId`).
- In `findOrCreateConversation(accountId, userId, contactId)` → add `whatsappConfigId`:
  - **Lookup:** add `.eq('whatsapp_config_id', whatsappConfigId)` to the existing-conversation query.
  - **Insert:** add `whatsapp_config_id: whatsappConfigId` to the `.insert({...})`.
  - **Race re-resolve:** add the same `.eq(...)` to the unique-violation re-query.

*(No change needed to the config lookup itself — `phone_number_id` is still unique, so
`configRows` still resolves to exactly one row. The `configRows.length > 1` guard can stay.)*

### 4.2 Send — use the conversation's pinned number, not "the account's"
**File:** `src/lib/whatsapp/send-message.ts` (around lines 221–255)

- The conversation is already loaded (`.from('conversations').eq('id', conversationId)`).
  Also select `whatsapp_config_id` on it.
- Replace the config load:
  ```ts
  // BEFORE
  .from('whatsapp_config').select(...).eq('account_id', accountId).single()
  // AFTER
  .from('whatsapp_config').select(...).eq('id', conversation.whatsapp_config_id).single()
  ```
- Fallback: if `conversation.whatsapp_config_id` is null (legacy), fall back to the account's
  first active number and persist it onto the conversation.

### 4.3 Public-API send by phone — choose a number
**File:** `src/lib/whatsapp/resolve-conversation.ts` (+ `src/app/api/v1/messages`, `.../conversations`)

- `resolveConversationByPhone(db, accountId, phone, name)` currently assumes one config.
  Add an optional `whatsappConfigId` (or `from` E.164) param:
  - If provided → use it.
  - If omitted → pick the account's **default/primary** active number (add a `is_primary` flag
    on `whatsapp_config`, or "first active" rule).
- Pass it into find-or-create so the conversation is pinned.

### 4.4 Broadcasts — pick a sending number
**Files:** `src/lib/whatsapp/broadcast-core.ts`, `src/app/(dashboard)/broadcasts/new`, migration for `broadcasts.whatsapp_config_id`

- Add `broadcasts.whatsapp_config_id` so a campaign sends from a chosen number.
- Broadcast worker uses that number's config + counts toward its daily cap (ban-safety, Doc 13).

### 4.5 Types
**Files:** `src/types/*` (whatsapp config + conversation types)

- Add the new `whatsapp_config` fields and `conversations.whatsapp_config_id` to the TS types
  (or regenerate Supabase types).

### 4.6 Frontend
**Files:** `src/app/(dashboard)/settings/*` (WhatsApp settings), `src/app/(dashboard)/inbox/*`

- **Settings → WhatsApp:** change from a single-number form to a **list** — add/edit/remove
  numbers, each with label + `phone_number_id` + token + verify_token + assignment. (The
  encrypt/save path already exists; it just becomes multi-row.)
- **Inbox:** show which number a conversation is on; optional filter by number; when starting a
  new conversation, pick the sending number.
- **Number health panel** (new, [Doc 40](40-frontend-web-app.md)) — per-number quality/tier/usage
  + pause/resume (`outreach_status`).

---

## 5. Things to watch (gotchas)

- **RLS unaffected.** Tenancy is `account_id` via `is_account_member(...)`, not per-number.
  Multiple numbers under one account are all visible to that account's members — correct for A7
  (managers see all numbers). Per-agent scoping (agent sees only their chats) is a **separate**
  concern handled at the query/assignment layer, not by number.
- **`phone_number_id` stays UNIQUE** — do **not** drop it; the webhook relies on it to route.
- **Status callbacks** (`handleStatusUpdate`) key off `message_id` and don't need the number —
  no change.
- **Verify token** — the webhook GET already scans **all** configs' verify tokens, so multiple
  numbers verify fine with no change.
- **Contacts stay account-level** (one contact per phone per account). Only **conversations**
  become per-number. So the same person across two numbers = one contact, two conversations —
  ideal for duplicate detection.

---

## 6. Test plan (add to wacrm's vitest suite)

- [ ] Two configs under one account both save; `phone_number_id` stays unique.
- [ ] Inbound to number A creates a conversation pinned to A; inbound to number B (same contact)
      creates a **second** conversation pinned to B.
- [ ] Reply in conversation A goes out from number A; reply in B from number B.
- [ ] Legacy conversation with null `whatsapp_config_id` falls back + self-heals on next send.
- [ ] Public-API send with explicit `from` uses that number; without → default number.
- [ ] Broadcast sends from its selected number and increments that number's daily counter.
- [ ] RLS: a viewer/agent still sees account data per role; no cross-account leakage.

---

## 7. Effort estimate

| Piece | Effort |
|-------|--------|
| Migration 037 | 1–2 hrs |
| Webhook pin | 1–2 hrs |
| Send by pinned number | 1–2 hrs |
| Public API + broadcast number | 3–5 hrs |
| Settings multi-number UI | ~1 day |
| Inbox number display/filter + health panel | ~1 day |
| Tests | ~half day |

**Total: ~3–4 focused days.** Small blast radius because inbound routing is already number-first.

---

*Next: [Doc 92 — Local setup guide](92-local-setup-guide.md).*
