# Doc 53 — WhatsApp Message Cost Control

> Meta charges for WhatsApp messages by category and window. The system is designed to
> **minimise cost automatically** and show management exactly what is being spent.
> Related: [12 Window & Templates](12-window-and-templates.md) · [10 Cloud API](10-whatsapp-cloud-api.md) · [30 DB schema](30-database-schema.md)

---

## 1. Current pricing model (read this — it changed)

> ⚠️ Meta moved away from the old "per 24-hour conversation" model to **per-message pricing**
> and made service + in-window utility messages free. The engineer **must confirm the exact
> current UAE rates in Meta Business Manager before go-live**, because fees change over time.

Key facts to build around:

| Message kind | Billing (current model) |
|--------------|-------------------------|
| Customer → us (inbound) | Free |
| Our free-form reply **inside** the open 24h window (service) | **Free** |
| **Utility** template sent **inside** an open window | **Free** |
| **Utility** template that opens/re-opens a chat (window closed) | Paid (utility rate) |
| **Marketing** template | Paid (marketing rate, higher) |
| **Authentication** template | Paid (not used here) |

**Rule of thumb the system enforces:** *free-form-in-window > utility > marketing* (cheapest to
most expensive). Prefer the cheapest legal option every time.

---

## 2. How the system saves money (automatic)

1. **Always prefer free-form inside the open window.** The window logic ([Doc 12](12-window-and-templates.md))
   already forces this — free-form when open, template only when closed.
2. **Default to Utility over Marketing** whenever the message qualifies (re-open, follow-up,
   viewing confirm are Utility). Marketing only when it's genuinely promotional **and** the
   customer is `opted_in` ([Doc 13](13-consent-and-ban-safety.md)).
3. **Batch nudges:** don't send multiple templates where one re-open + free conversation does the job.
4. **Respect the window countdown:** the UI nudges agents to keep a conversation going while
   the window is open (free), instead of letting it close and paying to re-open.

---

## 3. Cost tagging (data)

Every outbound message is tagged at send time and recorded in **`message_costs`** ([Doc 30](30-database-schema.md) §2.12):

| Field | Meaning |
|-------|---------|
| `category` | service (free) / utility / marketing |
| `billable` | was it a paid message? |
| `est_cost` | estimated cost using the configured current rate |
| `number_id` | which number (per-number spend) |

Rates live in **config** (per category, UAE), set from Meta Business Manager at go-live and
editable when Meta changes them — so estimates stay close to the real bill.

---

## 4. The monthly cost report (dashboard)

Admin sees a report ([Doc 40](40-frontend-web-app.md) §4.7):

- **Free vs paid** message counts for the month.
- Breakdown by **category** (service / utility / marketing).
- **Per-number** spend (ties into number health / outreach volume).
- **Estimated total spend** (₮/AED) for the month.
- Trend vs previous months.

This keeps cost **always visible** so nobody sends paid templates carelessly.

---

## 5. Guardrails (optional, recommended)

- **Budget alert:** warn admin when estimated monthly spend crosses a set figure.
- **Marketing cap:** limit marketing-template volume per number/day (also helps ban-safety).
- **Anomaly flag:** spike in paid templates (e.g. an agent spamming re-opens) → surface for review.

---

## 6. Important caveat

`est_cost` is an **estimate** from configured rates — the **authoritative** number is Meta's
actual invoice. Keep the configured rates current, and treat the report as a management guide,
not an accounting ledger.

---

## 7. Testing checklist

- [ ] Free-form in-window send is tagged `service` / not billable.
- [ ] In-window utility template tagged not billable (per current rules).
- [ ] Window-closed template tagged billable with correct category.
- [ ] Marketing only sends to opted-in customers and is tagged marketing.
- [ ] Per-number and per-category totals aggregate correctly.
- [ ] Monthly report shows free vs paid + estimated spend.
- [ ] Rate change in config updates future estimates.

---

*Next: [Doc 60 — Bitrix24 Two-Way Sync](60-bitrix24-sync.md).*
