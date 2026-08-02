# Doc 50 — AI Intelligence (OpenAI)

> The AI reads each conversation and tells managers which customers are serious, what they
> want, and whether an agent is misbehaving — so energy goes where it matters.
> Related: [20 Backend](20-backend-architecture.md) · [30 DB schema](30-database-schema.md) · [52 Competitor detection](52-competitor-detection.md) · [70 Security](70-security-and-compliance.md)

---

## 1. What the AI decides (per customer)

| Signal | Values | Use |
|--------|--------|-----|
| **Sentiment** | positive / neutral / negative | mood at a glance |
| **Seriousness score** | 0–100 | real buyer/tenant vs time-waster |
| **Lead status** | hot / warm / cold | derived from score + threshold |
| **Intent** | buying / renting / browsing / competitor_fishing | what they actually want |
| **Behaviour flag** | none / rude / unprofessional / off_policy | quality monitoring of the **agent** |

> Intent = `competitor_fishing` is a **soft** AI signal; the hard competitor signal is the
> number-DB match in [Doc 52](52-competitor-detection.md). Both feed the competitor banner.

---

## 2. Provider & model

- **Provider:** OpenAI.
- **Model:** a small, fast, cheap model for scoring (e.g. `gpt-4o-mini` class) — this is a
  classification task, not creative writing, so a mini model is the right cost/quality point.
- **Structured output:** force **JSON** (response_format = json_object / JSON schema) so parsing
  is deterministic.

> Confirm the current best-value model at build time; keep the model name in config so it can
> be swapped without code changes.

---

## 3. When it runs (cost control — batching)

**Do not call the AI on every word.** Trigger scoring:
- after an **inbound customer** message (not on our own outbound), **and**
- **debounced/batched** — e.g. score at most once every N seconds per customer, or every
  3–4 new messages, whichever comes first.

This catches hot leads fast while keeping token spend low. Scoring runs in the **`ai` queue**
([Doc 20](20-backend-architecture.md) §4), never inline in the webhook.

---

## 4. Context sent to the model

- The **last K messages** of the conversation (e.g. last 10–15), both directions, with
  who-said-what and timestamps.
- Minimal customer context (community interest, budget) if known.
- **Not** the whole history every time — cap the context to control tokens.

**Privacy:** this text leaves our server to OpenAI. See §9 + [Doc 70](70-security-and-compliance.md) —
strip/avoid sending unnecessary PII, and record this processing for PDPL.

---

## 5. Prompt design

**System instruction (fixed):**
```
You are a lead-qualification assistant for a Dubai real-estate agency.
Read the recent WhatsApp conversation between an AGENT and a CUSTOMER.
Return ONLY valid JSON matching the schema. Do not add commentary.
Judge the CUSTOMER for sentiment, seriousness (0-100), lead status, and intent.
Separately, flag if the AGENT was rude/unprofessional/off-policy.
"competitor_fishing" = the customer is likely a rival agent probing for owner/property
details rather than a genuine buyer/tenant.
```

**Response schema:**
```json
{
  "sentiment": "positive | neutral | negative",
  "seriousness_score": 0,
  "lead_status": "hot | warm | cold",
  "intent": "buying | renting | browsing | competitor_fishing",
  "behaviour_flag": "none | rude | unprofessional | off_policy",
  "reason": "one short sentence"
}
```

**Robustness:**
- Validate with Zod; if JSON is malformed → one retry, then skip (never crash the pipeline).
- `lead_status` should agree with `seriousness_score` vs the admin **hot threshold** (`settings.hot_lead_threshold`); backend can recompute status from score to stay consistent.

---

## 6. What happens with the result

1. Insert a row in **`ai_scores`** (full `raw` JSON kept for audit).
2. Update the **latest** values on `customers` (sentiment, seriousness_score, lead_status, intent).
3. Push `lead:scored` over Socket.IO → agent card + manager hot-leads update live.
4. If `seriousness_score ≥ hot_lead_threshold` and it **newly** crossed → create a `hot_lead`
   **alert** and push `alert:hot_lead`: *"Serious customer — Agent X, Community Y."*
5. If `behaviour_flag ≠ none` → create a `behaviour` alert for the manager (coaching).
6. Write score + status to **Bitrix custom fields** ([Doc 60](60-bitrix24-sync.md)).

De-dupe alerts: only alert on a **new** crossing, not on every re-score, so managers aren't spammed.

---

## 7. Hot-lead threshold

- Stored in `settings.hot_lead_threshold` (default 70), editable by admin.
- Changing it re-derives lead status on read; historical `ai_scores` are unchanged.

---

## 8. Cost model

- Mini model + batching keeps this cheap. Rough control: one scoring call per customer per
  burst of messages, small context window.
- Track AI usage (tokens/calls) for a monthly internal cost view (optional, alongside [Doc 53](53-cost-control.md)).
- **Graceful degradation:** if OpenAI is down or rate-limited, messaging is unaffected — scores
  simply retry later from the queue.

---

## 9. Privacy & compliance (important)

- Customer conversation text is **personal data** under UAE **PDPL**; sending it to OpenAI is
  third-party processing.
- Controls: send the **minimum** needed context, avoid sending IDs/documents, define a
  **retention** policy for `ai_scores.raw`, and document this processing.
- Optional future: a regional/self-hosted model if data-residency becomes a hard requirement.
- See [Doc 70 — Security & Compliance](70-security-and-compliance.md).

---

## 10. Testing checklist

- [ ] Scoring triggers on inbound only, and is batched (not per word).
- [ ] Model returns valid JSON; malformed output is retried then skipped safely.
- [ ] `customers` shows latest score; `ai_scores` keeps history.
- [ ] Crossing the hot threshold fires exactly one alert (not repeated).
- [ ] Behaviour flag creates a manager alert.
- [ ] Score + status reach Bitrix custom fields.
- [ ] OpenAI outage does not block send/receive; scoring retries.
- [ ] Context is capped (token spend bounded); no full-history blowup.

---

*Next: [Doc 51 — Duplicate-Client Detection](51-duplicate-detection.md).*
