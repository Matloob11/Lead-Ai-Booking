# Doc 12 — 24-Hour Window & Template System

> The most important concept for daily adoption **and** cost. If re-opening a chat is not
> one click, agents fall back to personal WhatsApp. This doc defines the window logic and the
> template lifecycle.
> Related: [10 Cloud API](10-whatsapp-cloud-api.md) · [13 Consent & Ban-safety](13-consent-and-ban-safety.md) · [53 Cost control](53-cost-control.md)

---

## 1. The rule (how WhatsApp works)

- A customer messages us → a **24-hour service window** opens for that customer+number.
- **Inside the window:** we send any free-form message (text/media) — **free**.
- **After 24h of customer silence:** the window **closes**. We can only reach them with an
  **approved template** message — which is **paid** (unless it's a Utility template used
  inside a still-open window, which is free under current pricing).

**A7 reality:** customers go quiet for 2–3 days while the team finds the property. Re-opening
must be effortless — **one tap**.

---

## 2. Window state — how the backend computes it

Per customer we store `last_inbound_at` (timestamp of their most recent inbound message).

```
windowOpen = (now - last_inbound_at) < 24h
```

- On **every inbound** message → update `last_inbound_at = now` (window re-opens).
- The backend exposes the window state to the web app for each chat.
- A background check flips chats to "closed" as they cross 24h (or compute on read — simpler and always correct).

> Compute-on-read is preferred: derive `windowOpen` from `last_inbound_at` whenever the chat
> is loaded/rendered, so there is no stale flag to maintain.

---

## 3. What the agent sees (web app)

| Window state | UI |
|--------------|-----|
| 🟢 **Open** | "Open — reply freely." Free-text box + media button enabled. |
| ⚪ **Closed** | "Closed — send a template to re-open." Free-text box **disabled**; template menu shown. |

**No dead ends:** when closed, the text box is physically disabled and the template menu is
the only path — the agent cannot get stuck. ([Doc 40](40-frontend-web-app.md))

Countdown nicety: show remaining time while open (e.g. "Window closes in 3h 12m") so the
agent knows to keep the conversation going.

---

## 4. The send decision (backend enforces it)

When the app requests a send, the backend decides — the app never forces a type:

```
if windowOpen:
    send free-form (text/media)          # Doc 10 §5.1 / §6.2
else:
    require a template payload
    if no template chosen → reject with "window closed, pick a template"
    send approved template               # Doc 10 §5.2
```

This guarantees we never attempt an illegal free-form send outside the window (which Meta
would reject with error `131047`).

---

## 5. Templates — the starting set

| Template name | Purpose | Category | Variables |
|---------------|---------|----------|-----------|
| `welcome_intro` | First contact / greeting a new lead | Utility* | `{{1}}` name |
| `property_ready` | "We found properties matching your needs" (re-open) | Utility | `{{1}}` name |
| `follow_up` | Gentle follow-up after silence | Utility | `{{1}}` name |
| `viewing_confirm` | Confirm a viewing date/time | Utility | `{{1}}` name, `{{2}}` date/time |
| `document_request` | Ask for documents (Emirates ID, etc.) | Utility | `{{1}}` name |

\* `welcome_intro` is Utility if it's purely a service greeting; if it promotes listings it
becomes **Marketing** and requires prior opt-in ([Doc 13](13-consent-and-ban-safety.md)).

**Variants:** each template may have 2–3 worded versions for *variety* (kept fresh). This is
**not** a compliance mechanism — Meta judges the template's **quality rating** from recipient
reactions, not wording rotation. Store variants in `templates.versions` (jsonb).

---

## 6. Template lifecycle

```
draft  ──submit──►  Meta review  ──►  APPROVED   ──►  usable
                          │
                          └────────►  REJECTED   ──►  edit + resubmit
APPROVED  ──(bad quality / policy)──►  PAUSED / DISABLED  ──►  fix + re-request
```

- Approval takes **1–2 days** (sometimes minutes). Plan for it before go-live.
- Store `meta_status` on each template (`approved` / `pending` / `rejected` / `paused`).
- **Only `approved` templates appear in the agent's menu.**
- **Fallback plan** if a template is rejected/paused: hide it, alert admin, and rely on the
  remaining approved templates so agents are never blocked.

---

## 7. Template send flow (concrete)

1. Agent taps `property_ready` in the closed-window menu.
2. App calls backend `POST /chats/:customerId/send-template { template: "property_ready" }`.
3. Backend fills `{{1}}` = customer name (from DB), picks a variant, builds the Meta payload.
4. Backend sends via the customer's **pinned number** ([Doc 11](11-multi-number-management.md)).
5. Logs message with `is_template = true`, `template_name`, cost category.
6. When the customer replies → window re-opens → free-form chat resumes automatically.

---

## 8. Cost linkage

- Prefer free-form inside the open window whenever possible.
- When a template is required, default to **Utility** category (cheaper / free-in-window)
  over Marketing wherever the message qualifies.
- Every template send is tagged with its category for the monthly cost report ([Doc 53](53-cost-control.md)).

---

## 9. Admin controls

- Add / edit templates and their variants.
- Submit templates to Meta / track approval status.
- Enable/disable a template in the agent menu.
- Set default category per template.

---

## 10. Testing checklist

- [ ] Fresh inbound opens the window; free-text enabled.
- [ ] After 24h silence, free-text disabled + template menu shown.
- [ ] One tap sends the correct approved template with the name filled in.
- [ ] Customer reply re-opens the window; free chat resumes.
- [ ] Free-form send outside window is blocked by backend (not sent to Meta).
- [ ] Only `approved` templates appear in the menu.
- [ ] Rejected/paused template disappears + admin alerted.
- [ ] Template send is logged with category for cost reporting.

---

*Next: [Doc 13 — Consent & Ban-Safety](13-consent-and-ban-safety.md).*
