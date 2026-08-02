# Doc 60 — Bitrix24 Two-Way Sync

> Bitrix24 stays the company's **record of truth**. Agents never enter data twice — the backend
> keeps Bitrix updated automatically, and relevant Bitrix changes flow back.
> Related: [20 Backend](20-backend-architecture.md) · [30 DB schema](30-database-schema.md) · [50 AI](50-ai-intelligence.md)

---

## 1. Principle

- The **system** owns live WhatsApp conversations; **Bitrix24** owns the durable CRM record
  (contacts, deals, pipeline).
- Sync is **automatic** and runs in the **`bitrix` queue** with retries, so a slow/down CRM
  never blocks messaging ([Doc 20](20-backend-architecture.md) §4).

---

## 2. What syncs INTO Bitrix (system → CRM)

| From system | To Bitrix |
|-------------|-----------|
| New customer | Create/update a **Contact** (match by phone) |
| Conversation | Attach chat history to the contact (timeline comment / activity, or linked deal) |
| AI sentiment + seriousness + lead status + intent | **Custom fields** on the contact |
| Competitor flag, duplicate flag | Custom fields |
| Assigned agent, assigned number, last WhatsApp contact, consent state | Custom fields |
| Serious lead crosses threshold | Auto-create or move a **Deal** in the pipeline |

**Idempotent upsert:** always match an existing contact by normalised phone before creating,
and store the returned `bitrix_contact_id` on our `customers` row so future updates target the
same contact.

---

## 3. What syncs BACK (CRM → system) — two-way

Optional but supported via a Bitrix outbound webhook → our `POST /webhook/bitrix`:

| Bitrix change | Effect in system |
|---------------|------------------|
| Contact reassigned to another agent | Update `assigned_agent_id` (respecting least-access) |
| Deal stage moved | Reflect status where relevant |
| Contact merged/updated | Update local name/fields |

Keep the back-sync **narrow and explicit** to avoid loops (see §6).

---

## 4. How it connects

- **Bitrix24 REST API** via an **inbound webhook** on A7's on-prem Bitrix (already available).
- Two implementation options (pick per team preference):
  1. **Direct REST** from the backend `bitrix` service — most control.
  2. **n8n glue** — backend fires an event → **n8n workflow** → Bitrix action. Keeps heavy CRM
     logic out of core code and easy to change without redeploying the backend.
- Recommended: **n8n for the CRM-shaped workflows** (create contact, move deal, write fields),
  backend for the trigger + storing `bitrix_contact_id`.

Common REST methods: `crm.contact.list` / `crm.contact.add` / `crm.contact.update`,
`crm.deal.add` / `crm.deal.update`, `crm.timeline.comment.add`.

---

## 5. Custom fields to add in Bitrix

Create these on the Contact (and mirror key ones on Deal where useful):

- **Sentiment Score** (or sentiment label)
- **Seriousness Score** (0–100)
- **Lead Status** (Hot / Warm / Cold)
- **Intent** (buying / renting / browsing / competitor)
- **Is Competitor Agent** (Y/N)
- **Duplicate Alert** (Y/N)
- **Assigned Agent**
- **Assigned Number**
- **Last WhatsApp Contact** (datetime)
- **Consent State**

Store the Bitrix **field IDs** in backend config so mapping isn't hard-coded in logic.

---

## 6. Loop & conflict safety

- **Prevent echo loops:** tag system-originated updates so a back-sync of our own change is
  ignored (e.g. skip if the change source is us / within a debounce).
- **Source of truth per field:** live conversation fields (last contact, AI scores) = system
  wins; pipeline/deal ownership = Bitrix can win. Document which side is authoritative per field.
- **Retry + dead-letter:** failed Bitrix calls retry with backoff; persistent failures land in a
  dead-letter list for admin, without losing the WhatsApp data.

---

## 7. Sync triggers (when the backend fires a Bitrix job)

- New customer created → upsert contact.
- New message (throttled, e.g. batch per conversation) → append to timeline + update last-contact.
- AI re-score → update score/status fields.
- Competitor/duplicate flag set/cleared → update fields.
- Hot lead → create/move deal.
- Reassignment → update assigned-agent field.

---

## 8. Chat-history strategy

Attaching **every** message individually to Bitrix can flood the timeline. Options:
- **Summary + link:** post periodic summary comments and keep full transcript in our DB
  (recommended — Bitrix stays clean, our DB is the full log).
- **Full mirror:** append each message (heavier; only if the business insists on full CRM copy).

Pick one at build time; make it configurable.

---

## 9. Testing checklist

- [ ] New customer creates exactly one Bitrix contact (no duplicates on repeat messages).
- [ ] `bitrix_contact_id` is stored and reused for updates.
- [ ] AI score/status lands in the correct custom fields.
- [ ] Competitor/duplicate flags reach Bitrix.
- [ ] Hot lead creates/moves a deal.
- [ ] Bitrix down → messaging continues; jobs retry and eventually sync.
- [ ] Back-sync of reassignment updates the system without creating a loop.
- [ ] Timeline isn't flooded (summary strategy works).

---

*Next: [Doc 70 — Security & Compliance](70-security-and-compliance.md).*
