# Doc 11 — Multi-Number Management

> A7 runs **several** company WhatsApp numbers (per team / community / agent), not one.
> This doc defines how the backend registers numbers, routes messages to the right one, and
> keeps each number healthy.
> Related: [10 Cloud API](10-whatsapp-cloud-api.md) · [13 Consent & Ban-safety](13-consent-and-ban-safety.md) · [30 DB schema](30-database-schema.md)

---

## 1. Why multi-number

- **Capacity:** each number has a daily new-conversation cap (messaging tier). More numbers = more outreach headroom.
- **Segmentation:** a number can represent a team, a community (e.g. "Marina desk"), or an individual agent's line.
- **Risk isolation:** if one number's quality drops or it gets restricted, the others keep working.

**Core rule:** a customer always keeps talking to the **same number** for the life of the
relationship. We never switch a live conversation to another number.

---

## 2. The number registry (`whatsapp_numbers`)

Every company number is a row. Conceptual fields:

| Field | Meaning |
|-------|---------|
| `id` | Internal UUID |
| `phone_number_id` (PNID) | Meta's ID — used in every send call |
| `display_number` | Human-readable E.164 (e.g. +9715XXXXXXX) |
| `label` | "Marina desk", "Agent Ali", etc. |
| `assignment_type` | `team` \| `community` \| `agent` \| `pool` |
| `assigned_ref` | which team/community/agent this number serves |
| `quality_rating` | Green / Yellow / Red (from Meta) |
| `messaging_tier` | 250 / 1K / 10K / unlimited |
| `daily_conversations_used` | rolling 24h new-conversation count |
| `status` | `active` \| `paused` \| `restricted` |
| `warmup_stage` | for new numbers (see [Doc 13](13-consent-and-ban-safety.md)) |

> The **token** is shared (one System-User token can send from any PNID under the WABA), so
> only the PNID changes per number — not the auth.

---

## 3. Inbound routing — which number received it

The webhook payload carries `metadata.phone_number_id` — **that** tells us which company
number the customer messaged. Resolution steps:

1. Look up the `whatsapp_numbers` row by `phone_number_id`.
2. Find or create the `customer` (by `wa_number`).
3. Determine the **assigned agent**:
   - If the customer already has `assigned_agent_id` → keep it (continuity).
   - Else assign based on the number's `assignment_type`:
     - `agent` → that agent.
     - `team` / `community` → route by the team's assignment rule (round-robin / least-busy / manual).
     - `pool` → assignment engine picks (see §5).
4. Store `assigned_number_id` on the customer so all future replies use the same number.

---

## 4. Outbound number selection — which number to send from

Priority order when sending a reply:
1. **The customer's `assigned_number_id`** (always, for continuity).
2. If that number is `paused`/`restricted` → the message is **held** and an admin alert is
   raised (do not silently move the customer to another number — it breaks trust and the
   24h window context). Admin can consciously re-home the customer if needed.

For **first-contact / cold outreach** (no assigned number yet), the assignment engine picks
a number (§5) and pins it to the customer.

---

## 5. Assignment engine (for pools & new leads)

Selects a number + agent for a brand-new customer. Inputs & rules:

- **Eligibility:** number must be `active`, quality not `Red`, and under its daily cap.
- **Balance:** prefer the eligible number with the most remaining daily headroom (spreads load).
- **Warm-up aware:** a number in early `warmup_stage` gets a smaller share.
- **Community match:** if the lead has a known community interest, prefer that community's number/agent.
- **Agent load:** among candidate agents, prefer least-busy / round-robin (configurable in admin).

Output: `(assigned_number_id, assigned_agent_id)` pinned to the customer.

---

## 6. Per-number health & auto-pause

Each number is monitored independently:

- **Quality rating** synced from Meta → stored on the row. `Red` → **auto-pause cold outreach**
  on that number (inbound replies still allowed inside open windows).
- **Daily conversation counter** → when near the tier cap, the assignment engine stops
  routing *new* conversations to it (existing chats unaffected).
- **Restricted status** (Meta flagged/blocked the number) → mark `restricted`, alert admin,
  hold outbound for its customers.

The **manager dashboard** shows a per-number panel: label, number, quality (🟢🟡🔴), tier,
today's usage vs cap, status — with **pause/resume** controls ([Doc 40](40-frontend-web-app.md)).

---

## 7. Admin controls for numbers

- Add a new number (enter PNID + label + assignment).
- Assign/re-assign a number to a team / community / agent.
- Pause / resume a number.
- Set warm-up stage / caps.
- View per-number usage + cost ([Doc 53](53-cost-control.md)).

---

## 8. Edge cases

| Case | Handling |
|------|----------|
| Same customer messages two *different* company numbers | Treat as one customer (key = `wa_number`); keep the first `assigned_number_id`; note the second contact. Possible duplicate/competitor signal. |
| Assigned number gets restricted mid-conversation | Hold outbound, alert admin, offer conscious re-home. |
| Number deleted/removed from WABA | Mark inactive; its customers need re-homing by admin. |
| Cold-outreach list larger than combined daily caps | Queue overflow to next day; never exceed per-number caps (ban-safety). |

---

## 9. Testing checklist

- [ ] Inbound message resolves to the correct number + assigned agent.
- [ ] Reply goes out from the customer's pinned number (never a different one).
- [ ] New lead gets a number+agent from the assignment engine respecting caps.
- [ ] `Red` quality number is auto-excluded from new outreach.
- [ ] Number at daily cap stops receiving *new* conversations but still serves existing chats.
- [ ] Paused number holds outbound + raises admin alert.
- [ ] Dashboard shows correct per-number health/usage.

---

*Next: [Doc 12 — 24-Hour Window & Templates](12-window-and-templates.md).*
