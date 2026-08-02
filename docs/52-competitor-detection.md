# Doc 52 — Competitor-Agent Detection

> Many "buyers" on Property Finder / Bayut are rival agents fishing for owner details to cut
> A7 out of the commission. A7 has a database of **30,000–100,000** agent numbers. The system
> checks every inbound number against it **before the agent even replies** and warns the agent.
> Related: [30 DB schema](30-database-schema.md) · [20 Backend](20-backend-architecture.md) · [50 AI](50-ai-intelligence.md) · [70 Security](70-security-and-compliance.md)

---

## 1. Purpose

Recognise **who is calling YOU** so the agent shares less, protects the owner's details, and
follows company policy. This is **defensive** identification — never a marketing list.

---

## 2. The data (`competitor_agents`)

- 30k–100k rows: `phone` (E.164, UNIQUE indexed), `source`, `whitelisted`, `added_at` ([Doc 30](30-database-schema.md) §2.8).
- **Fast lookup:** a single indexed equality check on `phone` → sub-millisecond even at 100k rows.
- `whitelisted = true` rows are treated as **not** competitors (false-positive overrides).

---

## 3. The logic (first step of the detection pipeline)

On **every** inbound message/call ([Doc 20](20-backend-architecture.md) §3.5, step 1) — before the agent replies:

```
match = SELECT 1 FROM competitor_agents
        WHERE phone = :incoming_number AND whitelisted = false;

if match:
    customers.is_competitor_agent = true
    create 'competitor' alert
    push alert:competitor  → agent app + dashboard
```

Because it runs first and is indexed, the **red banner shows before the agent even opens the
chat**.

---

## 4. What the agent sees

- A bold red banner in the chat window: **"THIS IS A COMPETITOR AGENT — protect owner details."**
- Guidance (short): share less, don't reveal owner contact, follow company policy on what not to disclose.
- The chat still works (we don't block it) — the agent just handles it carefully.

Managers also get the `competitor` alert in the dashboard feed.

---

## 5. Two signals, combined

| Signal | Source | Strength |
|--------|--------|----------|
| **Number match** | `competitor_agents` DB | **Hard** — definitive banner |
| **Behaviour / intent** | AI `intent = competitor_fishing` ([Doc 50](50-ai-intelligence.md)) | **Soft** — suggestion |

- Hard match → red banner immediately.
- Soft-only (not in DB but AI thinks it's an agent) → a lighter "possible competitor" hint,
  and the number can be **suggested** for admin review to add to the DB (§7).

---

## 6. Keeping the list fresh

- **Bulk upload:** admin uploads Excel/CSV any time → parsed, normalised to E.164, `COPY`/batch
  inserted with `ON CONFLICT (phone) DO NOTHING` (dedupe).
- **Whitelist / remove:** if a flagged "agent" is actually a real buyer, admin whitelists or
  removes them → banner stops.
- **Normalisation is critical:** strip spaces/`+`/`00`, standardise country code, so
  `+971 50 123 4567` and `0501234567` match the same stored value.

---

## 7. Optional AI-assisted suggestions (manual-review by default)

- When a caller behaves like an agent (AI `intent = competitor_fishing`), the system can
  **suggest** adding the number to the competitor DB.
- **Default = manual review**, not auto-add — auto-adding risks flagging a real buyer as a
  competitor and losing the deal. Admin approves suggestions.

---

## 8. Compliance (must read)

- This database is used **defensively only** — to recognise who is contacting us and protect
  owner details.
- It must be handled under UAE **PDPL** (personal data) and **TDRA** telemarketing rules.
- **Never** use these numbers for unsolicited cold marketing. ([Doc 70](70-security-and-compliance.md))

---

## 9. CSV import format (example)

```csv
phone,source
971501234567,PropertyFinder scrape 2026
971559876543,Bayut agent list
```
- Backend validates each row, normalises `phone`, skips malformed, reports counts imported/skipped.
- Large files processed in the `media`/import worker so the UI stays responsive.

---

## 10. Testing checklist

- [ ] A known competitor number triggers the red banner **before** the agent replies.
- [ ] Lookup on 100k rows is sub-millisecond.
- [ ] Whitelisted number does **not** trigger the banner.
- [ ] CSV import normalises formats and dedupes (no duplicate phones).
- [ ] `0501234567` and `+971501234567` match the same stored number.
- [ ] AI-only suspicion produces a suggestion, not an auto-add.
- [ ] Competitor flag reaches Bitrix custom field.

---

*Next: [Doc 53 — Cost Control](53-cost-control.md).*
