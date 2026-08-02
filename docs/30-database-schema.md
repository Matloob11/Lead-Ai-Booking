# Doc 30 — Database Schema (PostgreSQL)

> The full relational model. Everything else references this. Includes the fixes missing from
> the original spec: **multi-number, media, message status, consent, audit log, alerts,
> message-cost tracking.**
> Related: [11 Multi-number](11-multi-number-management.md) · [12 Window & Templates](12-window-and-templates.md) · [13 Consent](13-consent-and-ban-safety.md) · [20 Backend](20-backend-architecture.md)

---

## 1. ER overview

```
teams ──< agents ──< customers ──< messages
                 │        │  \
whatsapp_numbers <┘        │   └──< ai_scores
        │                  │
        └──────────────────┘ (assigned_number_id)

customers ──< consents          templates (independent)
customers ──< alerts            competitor_agents (independent, indexed)
agents/admin ──< audit_log      settings (singleton)
messages ──< message_costs      outreach_campaigns ──< outreach_targets
```

**Conventions:** UUID primary keys (`gen_random_uuid()` via `pgcrypto`), `timestamptz` for all
times (store UTC), phone numbers as **E.164 text without `+`** (e.g. `9715XXXXXXX`) for
consistent matching, soft-delete via `active`/`status` rather than hard deletes where history matters.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fast search on names/numbers
```

---

## 2. Tables

### 2.1 teams
```sql
CREATE TABLE teams (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.2 agents
```sql
CREATE TABLE agents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  email         TEXT UNIQUE NOT NULL,            -- login
  password_hash TEXT NOT NULL,                   -- bcrypt/argon2
  phone         TEXT,                            -- info only, not used to send
  role          TEXT NOT NULL CHECK (role IN ('agent','manager','admin')),
  team_id       UUID REFERENCES teams(id),
  community     TEXT,                            -- assigned pod/community
  active        BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agents_team ON agents(team_id);
```

### 2.3 whatsapp_numbers  *(new — multi-number)*
```sql
CREATE TABLE whatsapp_numbers (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number_id          TEXT UNIQUE NOT NULL,   -- Meta PNID
  display_number           TEXT NOT NULL,          -- E.164
  label                    TEXT,
  assignment_type          TEXT NOT NULL CHECK (assignment_type IN ('team','community','agent','pool')),
  assigned_team_id         UUID REFERENCES teams(id),
  assigned_agent_id        UUID REFERENCES agents(id),
  assigned_community       TEXT,
  quality_rating           TEXT DEFAULT 'unknown' CHECK (quality_rating IN ('green','yellow','red','unknown')),
  messaging_tier           TEXT DEFAULT 'tier_250',
  daily_conversations_used INT  NOT NULL DEFAULT 0,
  daily_reset_at           TIMESTAMPTZ,
  warmup_stage             TEXT DEFAULT 'new' CHECK (warmup_stage IN ('new','warming','established')),
  status                   TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','restricted')),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.4 customers
```sql
CREATE TABLE customers (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wa_number          TEXT UNIQUE NOT NULL,          -- E.164, dedupe key
  name               TEXT,
  assigned_agent_id  UUID REFERENCES agents(id),
  assigned_number_id UUID REFERENCES whatsapp_numbers(id),
  bitrix_contact_id  TEXT,
  community_interest TEXT,
  budget             TEXT,
  sentiment          TEXT CHECK (sentiment IN ('positive','neutral','negative')),
  seriousness_score  INT CHECK (seriousness_score BETWEEN 0 AND 100),
  lead_status        TEXT CHECK (lead_status IN ('hot','warm','cold')),
  intent             TEXT,                          -- buying/renting/browsing/competitor
  is_competitor_agent BOOLEAN NOT NULL DEFAULT false,
  duplicate_flag     BOOLEAN NOT NULL DEFAULT false,
  consent_state      TEXT NOT NULL DEFAULT 'none' CHECK (consent_state IN ('opted_in','implied','none','opted_out')),
  consent_source     TEXT,
  consent_at         TIMESTAMPTZ,
  opt_out_at         TIMESTAMPTZ,
  last_inbound_at    TIMESTAMPTZ,                   -- drives the 24h window
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_customers_agent  ON customers(assigned_agent_id);
CREATE INDEX idx_customers_status ON customers(lead_status);
CREATE INDEX idx_customers_name_trgm ON customers USING gin (name gin_trgm_ops);
```

### 2.5 messages
```sql
CREATE TABLE messages (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id    UUID NOT NULL REFERENCES customers(id),
  agent_id       UUID REFERENCES agents(id),          -- null if inbound
  number_id      UUID REFERENCES whatsapp_numbers(id),-- which number handled it
  direction      TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  type           TEXT NOT NULL DEFAULT 'text',        -- text/image/document/audio/video/template
  body           TEXT,
  media_url      TEXT,                                -- storage key/URL (new)
  media_type     TEXT,                                -- mime (new)
  is_template    BOOLEAN NOT NULL DEFAULT false,
  template_name  TEXT,
  wa_message_id  TEXT UNIQUE,                         -- idempotency + status mapping
  status         TEXT DEFAULT 'received'
                 CHECK (status IN ('received','queued','sent','delivered','read','failed')),
  error_code     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_customer ON messages(customer_id, created_at);
CREATE INDEX idx_messages_status   ON messages(status);
```

### 2.6 ai_scores  *(history of AI judgements)*
```sql
CREATE TABLE ai_scores (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id       UUID NOT NULL REFERENCES customers(id),
  sentiment         TEXT,
  seriousness_score INT CHECK (seriousness_score BETWEEN 0 AND 100),
  lead_status       TEXT,
  intent            TEXT,
  behaviour_flag    TEXT,                 -- rude/unprofessional/off-policy/null
  model             TEXT,                 -- e.g. gpt-4o-mini
  raw               JSONB,                -- full model JSON for audit
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_scores_customer ON ai_scores(customer_id, created_at);
```
> `customers` holds the **latest** score for fast reads; `ai_scores` holds the **history**.

### 2.7 templates
```sql
CREATE TABLE templates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT UNIQUE NOT NULL,      -- Meta template name
  category     TEXT NOT NULL CHECK (category IN ('utility','marketing','authentication')),
  language     TEXT NOT NULL DEFAULT 'en',
  versions     JSONB NOT NULL,            -- rotating worded variants
  variables    JSONB,                     -- e.g. ["name","datetime"]
  meta_status  TEXT NOT NULL DEFAULT 'pending' CHECK (meta_status IN ('pending','approved','rejected','paused')),
  enabled      BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.8 competitor_agents  *(30k–100k rows, must be fast)*
```sql
CREATE TABLE competitor_agents (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone      TEXT UNIQUE NOT NULL,        -- E.164
  source     TEXT,                        -- where the number came from
  whitelisted BOOLEAN NOT NULL DEFAULT false,
  added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_competitor_phone ON competitor_agents(phone);  -- O(1)-ish lookup
```
> Lookup is a single indexed equality check → instant even at 100k rows.

### 2.9 consents  *(opt-in log / history)*
```sql
CREATE TABLE consents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(id),
  state       TEXT NOT NULL,              -- opted_in/implied/opted_out
  source      TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.10 alerts
```sql
CREATE TABLE alerts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type        TEXT NOT NULL CHECK (type IN ('hot_lead','duplicate','competitor','behaviour','number_health')),
  customer_id UUID REFERENCES customers(id),
  agent_id    UUID REFERENCES agents(id),
  payload     JSONB,
  seen        BOOLEAN NOT NULL DEFAULT false,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_unseen ON alerts(seen, created_at);
```

### 2.11 audit_log  *(new — spec claimed audit but had no table)*
```sql
CREATE TABLE audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id    UUID REFERENCES agents(id),   -- who
  action      TEXT NOT NULL,                -- login/send/send_template/reassign/import/...
  target_type TEXT,                         -- customer/number/template/...
  target_id   TEXT,
  metadata    JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_actor ON audit_log(actor_id, created_at);
```

### 2.12 message_costs  *(cost reporting, Doc 53)*
```sql
CREATE TABLE message_costs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id  UUID REFERENCES messages(id),
  number_id   UUID REFERENCES whatsapp_numbers(id),
  category    TEXT,                          -- service(free)/utility/marketing
  billable    BOOLEAN NOT NULL DEFAULT false,
  est_cost    NUMERIC(10,4),                 -- estimated, rates confirmed at go-live
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.13 outreach_campaigns / outreach_targets  *(cold outreach, Doc 13)*
```sql
CREATE TABLE outreach_campaigns (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  template_id UUID REFERENCES templates(id),
  status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','running','paused','done')),
  created_by  UUID REFERENCES agents(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE outreach_targets (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id  UUID REFERENCES outreach_campaigns(id),
  customer_id  UUID REFERENCES customers(id),
  state        TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','sent','skipped','failed')),
  skip_reason  TEXT,
  sent_at      TIMESTAMPTZ
);
```

### 2.14 settings  *(singleton config editable by admin)*
```sql
CREATE TABLE settings (
  id                   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  hot_lead_threshold   INT NOT NULL DEFAULT 70,
  outreach_daily_cap   INT NOT NULL DEFAULT 100,
  window_hours         INT NOT NULL DEFAULT 24,
  extra                JSONB,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 3. Key relationships & rules

- A **customer** belongs to one **agent** and one **number** at a time (continuity). Re-assignment
  updates these + writes `audit_log`.
- **messages.wa_message_id** is `UNIQUE` → idempotent webhook handling; status callbacks map here.
- **customers.wa_number** is `UNIQUE` → one customer identity across numbers (duplicate/competitor logic).
- `customers` carries **latest** AI + flags for fast list rendering; full history in `ai_scores` / `messages`.
- **competitor_agents.phone** indexed for instant lookup on every inbound.

---

## 4. Window state query (no stored flag needed)

```sql
SELECT (now() - last_inbound_at) < (SELECT window_hours FROM settings) * INTERVAL '1 hour'
       AS window_open
FROM customers WHERE id = $1;
```

---

## 5. Migrations & seed

- Use **Prisma Migrate** or **Knex migrations** — never hand-edit prod schema.
- Seed data: one admin agent, the 5 starting templates (pending), the `settings` row.
- Competitor DB loaded via bulk CSV import ([Doc 52](52-competitor-detection.md)) — use `COPY` for speed.

---

## 6. Indexing summary

| Table | Index | For |
|-------|-------|-----|
| messages | (customer_id, created_at) | load a chat fast |
| messages | wa_message_id UNIQUE | idempotency + status map |
| customers | wa_number UNIQUE | identity/dedupe |
| customers | name (gin_trgm) | search |
| competitor_agents | phone UNIQUE | instant competitor lookup |
| alerts | (seen, created_at) | unseen feed |

---

## 7. Testing checklist

- [ ] Duplicate `wa_message_id` insert is ignored (idempotent).
- [ ] Window query returns correct open/closed around the 24h boundary.
- [ ] Competitor lookup on 100k rows is sub-millisecond.
- [ ] Re-assignment updates agent+number and writes an audit row.
- [ ] Customer identity stays single across two different company numbers.
- [ ] Latest score on `customers` matches most recent `ai_scores` row.

---

*Next: [Doc 40 — Frontend Web App](40-frontend-web-app.md).*
