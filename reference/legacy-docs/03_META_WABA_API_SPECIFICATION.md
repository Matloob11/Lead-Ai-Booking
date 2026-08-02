# 03 - Meta WhatsApp Business API Cloud Specification

## 1. Webhook Verification & HMAC Security
Meta WABA sends HTTP GET requests for initial webhook validation and HTTP POST requests for event notifications.

### GET Validation:
- Query Parameters: `hub.mode`, `hub.challenge`, `hub.verify_token`.
- System verifies `hub.verify_token == META_WEBHOOK_VERIFY_TOKEN` and echoes back `hub.challenge`.

### POST Signature Verification:
- Header: `X-Hub-Signature-256: sha256=<hash>`.
- System calculates SHA-256 HMAC of raw request body using `META_APP_SECRET` and rejects mismatched signatures (HTTP 401).

---

## 2. Meta Outbound API Endpoint (`/messages`)
- **Endpoint**: `https://graph.facebook.com/v19.0/{phone_number_id}/messages`
- **Headers**:
  - `Authorization: Bearer {waba_access_token}`
  - `Content-Type: application/json`

### Outbound Text Payload Example:
```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "971501234567",
  "type": "text",
  "text": {
    "preview_url": false,
    "body": "Hello, thank you for contacting A7 Group."
  }
}
```

### Outbound Template (HSM) Payload Example:
```json
{
  "messaging_product": "whatsapp",
  "to": "971501234567",
  "type": "template",
  "template": {
    "name": "payment_reminder_v1",
    "language": { "code": "en" },
    "components": [
      {
        "type": "body",
        "parameters": [
          { "type": "text", "text": "John Doe" },
          { "type": "text", "text": "AED 1,500" }
        ]
      }
    ]
  }
}
```

---

## 3. Status Callbacks (`sent`, `delivered`, `read`, `failed`)
Meta posts status updates for every outbound message:
- `statuses.status`: `"sent"` | `"delivered"` | `"read"` | `"failed"`
- System updates `waba_message_log` and notifies Bitrix via `imconnector.send.status`.
