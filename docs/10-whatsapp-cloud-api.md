# Doc 10 — WhatsApp Cloud API Layer

> Detailed build guide for the WhatsApp integration. This is the pipe between customers and
> our backend. **Only the backend touches this layer** — never the web app.
> Related: [11 Multi-number](11-multi-number-management.md) · [12 Window & Templates](12-window-and-templates.md) · [13 Consent & Ban-safety](13-consent-and-ban-safety.md)

---

## 1. What this layer does

- Receives every inbound customer message and status update from Meta (via **webhook**).
- Sends outbound messages (free-form and template) from our company numbers.
- Uploads/downloads **media**.
- Reports each number's **health** (quality rating, messaging tier).

All of it runs on the backend using the **official Meta WhatsApp Business Cloud API** over
the Graph API.

```
Meta Cloud API  ──(webhook POST)──►  Backend /webhook/whatsapp
Backend  ──(POST /{PNID}/messages)──►  Meta Cloud API  ──►  Customer
```

---

## 2. Prerequisites (get these from the webbox / allots.io panel + Meta)

| Item | What it is | Where from |
|------|-----------|------------|
| **WABA ID** | WhatsApp Business Account ID (owns the numbers) | Meta Business Manager / panel |
| **Business ID** | Meta Business portfolio ID | Panel |
| **Phone Number ID (PNID)** | One per WhatsApp number — used in every send call | Panel / Meta → one per number |
| **Permanent access token** | System-User token that never expires | Meta Business → System User → generate |
| **App ID + App Secret** | Needed to **verify webhook signatures** | Meta App dashboard |
| **Verify token** | A secret string we invent for webhook setup | We choose it |

> ⚠️ **Permanent token, not temporary.** Generate a **System User** token with
> `whatsapp_business_messaging` + `whatsapp_business_management` permissions so the
> connection never expires. Store all of these as backend env vars (see §11).

---

## 3. Webhook — one-time verification (GET)

When we register the webhook URL in Meta, Meta sends a single **GET** to prove we own it.

```
GET /webhook/whatsapp?hub.mode=subscribe&hub.verify_token=<OUR_VERIFY_TOKEN>&hub.challenge=<random>
```

Backend logic:
```
if (hub.mode === 'subscribe' && hub.verify_token === env.WA_VERIFY_TOKEN) {
    respond 200 with the raw hub.challenge value
} else {
    respond 403
}
```

Subscribe the webhook to these fields: **`messages`** (covers inbound messages **and**
message status callbacks).

---

## 4. Webhook — receiving events (POST) + signature verification

Every inbound message and every status update arrives as a **POST** to the same URL.

### 4.1 Verify the signature FIRST (mandatory)

Meta signs each POST body:
```
X-Hub-Signature-256: sha256=<hmac>
```
We recompute `HMAC-SHA256(rawBody, APP_SECRET)` and compare (timing-safe). **If it does not
match, reject with 401 and drop the request.** Without this, anyone can POST fake messages
to our public URL.

```
Important: compute the HMAC over the EXACT raw request body bytes, before any JSON
parsing/re-serialisation. Configure Express to keep the raw body on this route.
```

### 4.2 Respond fast, process async

Meta expects a **200 within a few seconds** or it retries (causing duplicates). So:
1. Verify signature.
2. Immediately return `200 OK`.
3. Push the payload onto an internal **queue/worker** for the real processing (DB, AI, Bitrix).

### 4.3 Inbound message payload (shape)

```jsonc
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "<WABA_ID>",
    "changes": [{
      "field": "messages",
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "9715XXXXXXX",
          "phone_number_id": "<PNID>"          // ← which of OUR numbers received it
        },
        "contacts": [{ "profile": { "name": "Ali" }, "wa_id": "9715YYYYYYY" }],
        "messages": [{
          "from": "9715YYYYYYY",               // customer number (E.164, no +)
          "id": "wamid.HBg...",                // WhatsApp message ID (idempotency key)
          "timestamp": "1731000000",
          "type": "text",                      // text | image | document | audio | video | interactive | button
          "text": { "body": "Do you have 2BHK in Marina?" }
        }]
      }
    }]
  }]
}
```

**Per inbound message the backend must capture:** `phone_number_id` (which number),
`from` (customer), `id` (wamid), `timestamp`, `type`, and the content (text or media ref).
Then run the detection pipeline (competitor → duplicate → AI).

### 4.4 Idempotency

Use `messages[].id` (the `wamid`) as a **unique key** — Meta can deliver the same webhook
twice. Insert with `ON CONFLICT (wa_message_id) DO NOTHING` so retries never create duplicates.

### 4.5 Status callback payload (delivery receipts)

```jsonc
{
  "value": {
    "statuses": [{
      "id": "wamid.HBg...",        // the OUTBOUND message id we sent earlier
      "status": "delivered",       // sent | delivered | read | failed
      "timestamp": "1731000050",
      "recipient_id": "9715YYYYYYY",
      "errors": [ /* present when status = failed */ ]
    }]
  }
}
```
Map `id` → our stored message → update its `status` column → push `message:status` to the UI
so the ticks update live. On `failed`, log the error code and surface it (§8).

---

## 5. Sending messages

Endpoint (per number — this is where multi-number lives):
```
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
Authorization: Bearer <PERMANENT_TOKEN>
Content-Type: application/json
```

### 5.1 Free-form text (only inside the open 24h window)

```jsonc
{
  "messaging_product": "whatsapp",
  "to": "9715YYYYYYY",
  "type": "text",
  "text": { "body": "Yes — sending you 3 options now." }
}
```

### 5.2 Template message (to start / re-open outside the window)

```jsonc
{
  "messaging_product": "whatsapp",
  "to": "9715YYYYYYY",
  "type": "template",
  "template": {
    "name": "property_ready",
    "language": { "code": "en" },
    "components": [{
      "type": "body",
      "parameters": [{ "type": "text", "text": "Ali" }]   // fills {{1}} = customer name
    }]
  }
}
```

### 5.3 Response

```jsonc
{ "messages": [{ "id": "wamid.HBg..." }] }   // ← save this id; status callbacks reference it
```

> **The backend decides text vs template**, not the agent. It checks `last_inbound_at`:
> window open → allow §5.1; window closed → force §5.2. See [Doc 12](12-window-and-templates.md).

---

## 6. Media handling

### 6.1 Inbound media (customer sends a photo/PDF/voice)

The webhook gives a **media id**, not the file:
```jsonc
"image": { "id": "<MEDIA_ID>", "mime_type": "image/jpeg", "sha256": "..." }
```
Download flow (backend, async):
1. `GET /v21.0/{MEDIA_ID}` (with Bearer token) → returns a short-lived `url`.
2. `GET <url>` (with Bearer token) → the actual bytes.
3. Save via the **storage driver** (local disk / S3 / R2) → store `media_url` + `media_type` on the message.

> Media URLs from Meta expire fast — download promptly in the worker.

### 6.2 Outbound media (agent sends a file)

1. Web app uploads the file to **our backend** (not Meta).
2. Backend `POST /v21.0/{PNID}/media` (multipart) → gets a Meta **media id**.
3. `POST /{PNID}/messages` with that id:
```jsonc
{ "messaging_product":"whatsapp", "to":"9715YYYYYYY", "type":"image",
  "image": { "id":"<UPLOADED_MEDIA_ID>", "caption":"Marina 2BHK" } }
```

**Supported types:** image, document (PDF), audio/voice, video — respect Meta's per-type
size limits (documented in Doc 80 checklist).

---

## 7. Message types we handle

| Type | Inbound | Outbound |
|------|---------|----------|
| text | ✅ | ✅ (window open) |
| image / document / audio / video | ✅ download + store | ✅ upload + send |
| template | — | ✅ (window closed / first contact) |
| interactive (buttons/list) | ✅ (button replies) | optional (phase 2) |
| location / contacts | store as-is | optional |

---

## 8. Errors, retries & failures

- **Send errors** come back with a Meta error `code` + `message`. Common ones to handle:
  - `131047` — re-engagement required (window closed) → switch to template.
  - `131026` — message undeliverable (number not on WhatsApp) → mark customer invalid.
  - `368 / 131031` — account/number restricted → pause that number, alert admin.
  - `130429` — rate limit hit → back off + retry with jitter.
- **Retry policy:** exponential backoff for transient (5xx / rate-limit); **no retry** for
  permanent errors (invalid number, template rejected).
- **Failed status callback:** update message → `failed`, show a red indicator in the UI, and
  (if it was a window issue) offer the template path.

---

## 9. Rate limits & messaging tiers (per number)

- **Messaging tier** caps how many **unique customers** a number can *start* conversations
  with per rolling 24h: **250 → 1K → 10K → unlimited**. Tier rises automatically as the
  number maintains good quality + volume.
- **API throughput** also has an upper cap (messages/second) — our queue/worker paces sends.
- The backend tracks per-number daily new-conversation count and **stops before the cap**,
  spilling to other numbers or queuing (see [Doc 11](11-multi-number-management.md)).

---

## 10. Quality rating (per number)

- Meta assigns each number **Green / Yellow / Red** based on how recipients react (blocks,
  reports, "not useful").
- We read quality from the webhook (`account_update` / phone-number health) or Business
  Manager and store it on `whatsapp_numbers`.
- **Red → auto-pause** cold outreach on that number (ban-safety, [Doc 13](13-consent-and-ban-safety.md)).

---

## 11. Environment variables (backend only)

```
WA_GRAPH_VERSION=v21.0
WA_PERMANENT_TOKEN=<system-user token>
WA_APP_SECRET=<for X-Hub-Signature-256 verification>
WA_VERIFY_TOKEN=<our chosen webhook verify string>
WA_WABA_ID=<waba id>
# Phone Number IDs are stored in the whatsapp_numbers DB table, not env (multi-number).
```

Never ship any of these to the browser or CRM.

---

## 12. Endpoints this layer exposes/consumes

**Backend exposes (to Meta):**
- `GET  /webhook/whatsapp` — verification challenge.
- `POST /webhook/whatsapp` — inbound messages + statuses (signature-verified).

**Backend consumes (from Meta Graph):**
- `POST /{PNID}/messages` — send.
- `POST /{PNID}/media` — upload media.
- `GET  /{MEDIA_ID}` → `GET <url>` — download media.
- `GET  /{WABA_ID}/phone_numbers` — list numbers + quality/tier (for the number registry).

---

## 13. Testing checklist for this layer

- [ ] Webhook verification (GET challenge) succeeds.
- [ ] Forged POST (bad signature) is rejected with 401.
- [ ] Real inbound text appears in DB with correct `phone_number_id` + `wamid`.
- [ ] Duplicate webhook (same wamid) does **not** create a second row.
- [ ] Outbound text delivers from the **correct company number**.
- [ ] Window-closed send is blocked and template path is used instead.
- [ ] Inbound image/PDF/voice is downloaded and stored; URL shows in UI.
- [ ] Outbound media uploads and delivers.
- [ ] Status callbacks flip a message sent → delivered → read live.
- [ ] Failed send shows a red state + logged error code.
- [ ] Per-number tier/quality is read and stored.

---

*Next: [Doc 11 — Multi-number management](11-multi-number-management.md).*
