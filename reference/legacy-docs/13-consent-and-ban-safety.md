# Doc 13 — Consent (Opt-in) & Ban-Safety

> A7 does **cold outreach** (messaging new Property Finder / Bayut leads first) **and**
> incoming replies. Cold outreach is the single biggest way to get a number **banned**. This
> doc defines the consent model and the safety controls that protect every number.
> Related: [11 Multi-number](11-multi-number-management.md) · [12 Window & Templates](12-window-and-templates.md) · [70 Security & Compliance](70-security-and-compliance.md)

---

## 1. Why this matters

Messaging people who never asked to hear from us → they tap **Block** or **Report**. Meta
watches this. Enough of it and the number's **quality rating drops** (Green → Yellow → Red),
its **messaging tier is cut**, and eventually the number is **banned**. A banned number =
lost conversations, lost history, business disruption. So safety is built into the system.

Also legally: UAE **PDPL** (personal data) and **TDRA** telemarketing rules apply. Unsolicited
marketing is restricted. ([Doc 70](70-security-and-compliance.md))

---

## 2. Consent model

Every customer carries a consent record:

| Field | Meaning |
|-------|---------|
| `consent_state` | `opted_in` \| `implied` \| `none` \| `opted_out` |
| `consent_source` | where it came from: "PropertyFinder enquiry", "Bayut lead", "web form", "walk-in", "referral" |
| `consent_at` | timestamp |
| `opt_out_at` | set if the customer replied STOP / asked to stop |

**States explained:**
- **opted_in** — customer explicitly agreed (form checkbox, replied YES, gave number for contact). Safe for outreach incl. Marketing.
- **implied** — the customer *enquired about a specific property* on a portal → reasonable basis to reply about **that** enquiry with a **Utility** template. Not a licence for promotional blasts.
- **none** — no basis. **Do not cold-message.**
- **opted_out** — they asked to stop. **Never message again** (except a final confirmation).

---

## 3. First-contact rules (cold outreach)

1. **Templates only.** First contact outside any window must be an **approved template**
   ([Doc 12](12-window-and-templates.md)). Free-form first contact is impossible anyway (no window).
2. **Right category:**
   - Enquiry-based (implied consent) → **Utility** template about their enquiry.
   - Promotional / new-listing push → **Marketing** template → **requires `opted_in`**.
3. **Opt-out line.** Outreach templates should make it easy to stop ("Reply STOP to opt out").
4. **Consent captured before sending.** The outreach engine refuses to send if `consent_state`
   is `none` or `opted_out`.

**Opt-out handling:** if an inbound message is STOP / "don't message" / similar → set
`opted_out`, stop all outreach, alert the agent. (Simple keyword + optional AI intent check.)

---

## 4. Number warm-up (new numbers)

A brand-new number must not blast on day one — that is the fastest way to a ban.

| warmup_stage | Daily new-conversation ceiling (guide) | Notes |
|--------------|----------------------------------------|-------|
| `new` (days 1–3) | very low (e.g. ≤ 20–50) | mostly replies to inbound; tiny outreach |
| `warming` (week 1–2) | ramp gradually | grow only if quality stays Green |
| `established` | up to Meta tier cap | full outreach |

- Ramp **with** the Meta messaging tier (250 → 1K → 10K → unlimited), never ahead of it.
- If quality dips during warm-up → **hold/step back**, don't push.

---

## 5. Per-number quality monitoring & auto-pause

- Sync each number's **quality rating** from Meta into `whatsapp_numbers.quality_rating`.
- **Rule:** `Red` → **auto-pause cold outreach** on that number immediately (inbound replies
  inside open windows still allowed). Alert admin.
- `Yellow` → warn admin, reduce outreach volume on that number.
- The dashboard shows live per-number health with pause/resume ([Doc 40](40-frontend-web-app.md)).

---

## 6. Rate limiting & pacing

- **Per-number caps:** max new conversations per hour/day (below the tier cap, with margin).
- **Global pacing:** the outreach worker spreads sends over time (no bursts).
- **Overflow:** if the outreach list exceeds combined daily capacity, queue the remainder to
  the next day — **never** exceed a number's cap to "get it done".
- **Distribution:** spread a campaign across multiple healthy numbers rather than hammering one.

---

## 7. Block / report / failure signals

Watch these and back off automatically:
- Rising `failed` statuses or delivery drops on a number → reduce its outreach, alert admin.
- Meta `restricted` status on a number → stop outbound, alert admin ([Doc 11](11-multi-number-management.md) §8).
- Spike in opt-outs after a campaign → pause that campaign/template, review wording.

---

## 8. The outreach engine (putting it together)

For each lead in an outreach batch, the engine checks — in order — and **skips** on any fail:

```
1. consent_state ∈ {opted_in, implied}        else skip (log reason)
2. not opted_out                              else skip
3. target number: active, quality ≠ Red        else pick another / defer
4. number under daily cap + warmup ceiling      else defer to tomorrow
5. approved template of the right category exists else skip
6. pace within rate limit                        else queue
→ send template, pin number+agent, log consent basis + template + category
```

Every send records **why it was allowed** (consent basis) for audit ([Doc 70](70-security-and-compliance.md)).

---

## 9. Admin controls

- Import leads with their consent source (so `consent_state` is set correctly on import).
- Set per-number warm-up stage + caps.
- Set global outreach pacing / daily limits.
- Pause/resume outreach globally, per number, or per campaign.
- View opt-out list; honour it permanently.

---

## 10. Testing checklist

- [ ] Lead with `consent_state = none` is **not** cold-messaged.
- [ ] Enquiry lead (implied) gets a **Utility** template, not Marketing.
- [ ] Marketing template only sends to `opted_in` leads.
- [ ] Inbound "STOP" sets `opted_out` and blocks all future outreach.
- [ ] New number obeys warm-up ceiling, not the full tier cap.
- [ ] `Red` quality number auto-pauses cold outreach; inbound replies still work.
- [ ] Outreach batch bigger than daily capacity defers overflow to next day.
- [ ] Every outreach send logs its consent basis + template + category.

---

*Next: [Doc 20 — Backend Architecture](20-backend-architecture.md).*
