# 02 - Bitrix24 Open Channels Connector Technical Specification

## 1. Bitrix24 Local App Scopes & Authentication
The integration hub registers a Local Application inside Bitrix24 with the following required REST API permissions:
- `imconnector`: Custom channel connector registration and message relay.
- `imopenlines`: Open Channels configuration and routing rules.
- `crm`: Lead/Contact lookup, creation, and binding.
- `contact_center`: Display custom connector icon in Bitrix Contact Center dashboard.

---

## 2. Inbound Message Workflow (Customer -> Meta -> Bitrix)

```
Customer (WhatsApp) ──> Meta Webhook ──> A7 Integration Engine ──> Bitrix imconnector.send.messages
                                                                           │
                                                                           ▼
                                                                  Bitrix Open Channel Chat
                                                                  (Lead/Contact Created/Updated)
```

### Steps:
1. **Meta Webhook Intake**: Received at `/api/v1/waba/webhook/`.
2. **Phone Number Lookup**: Extract `display_phone_number` / `phone_number_id` and match with `waba_channel` table.
3. **Session Window Reset**: Update `waba_session.last_customer_message_at = utc_now()`.
4. **CRM Lead Matching**: Query `crm.duplicate.findbycomm` for customer phone. Create Lead if no match exists.
5. **Bitrix Message Delivery**: Post message payload via `imconnector.send.messages` API.

---

## 3. Outbound Message Workflow (Agent -> Bitrix -> Meta)

```
Bitrix Agent Reply ──> ONIMCONNECTORMESSAGEADD Webhook ──> Session Window Check ──> Meta Graph API (/messages)
                                                                                         │
                                                                                         ▼
                                                                                  Customer Phone
```

### Outbound Logic:
1. Bitrix emits `ONIMCONNECTORMESSAGEADD` webhook when an agent replies.
2. A7 Engine checks `waba_session` for active 24h window:
   - **If Active**: Send free-form text or media to Meta WABA `/messages` API.
   - **If Expired**: Return error event to Bitrix chat informing agent to use the Template Sender UI Widget.
3. Upon Meta API response, report status back to Bitrix via `imconnector.send.status`.
