# A7 Group WhatsApp Business API (Omni Channel) System Architecture

## 1. System Overview

The A7 Group WhatsApp Business API System connects Meta WhatsApp Business API (via the ALOTS.IO standard endpoint protocol) with Bitrix24 Contact Center Open Channels. It allows 50+ real estate agents to communicate with clients using the official company WhatsApp number(s) directly from Bitrix Chat UI while giving supervisors 100% audit, compliance, and live monitoring oversight.

```
+-----------------------------------------------------------------------------------+
|                                  CLIENT WHATSAPP                                  |
+-----------------------------------------------------------------------------------+
                                   ^            |
               (24h Freeform Chat  |            | (Inbound Webhook
               / Template Msg)     |            v  POST /api/v1/meta/webhook)
+----------------------------------+------------+-----------------------------------+
|               ALOTS.IO / Meta WABA Cloud API Gateway                              |
+-----------------------------------------------+-----------------------------------+
                                                |
                                                v
+-----------------------------------------------+-----------------------------------+
|          LOCAL BACKEND CONNECTOR SERVICE (Python FastAPI)                        |
|                                                                                   |
|  - Webhook Listener & Payload Transformer                                         |
|  - 24-Hour Session Window State Manager (SQLite)                                  |
|  - 50-Agent Phone-to-Open-Line Router                                             |
|  - Bitrix `imconnector` Protocol Engine (`imconnector.send.messages`)            |
|  - Outbound Webhook Handler (`ONIMCONNECTORMESSAGEADD`)                           |
|  - Template Proxy Engine (`GET /message_templates` & `POST /messages`)           |
+-----------------------------------------------+-----------------------------------+
         ^                                      |
         | (Outbound Message /                   | (Inbound Chat Delivery
         |  Template Trigger)                   v  to Agent Open Line)
+--------+--------------------------------------+-----------------------------------+
|                      BITRIX24 CONTACT CENTER & CRM                                |
|                                                                                   |
|  - Agent View: Bitrix Chat UI (Assigned Open Lines / Numbers only)                |
|  - Supervisor View: Full Live Monitoring across all 50 Agents                     |
|  - Outbound Template Sender Widget: Bitrix CRM App / Placement                    |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Operational Mechanics

### A. Multi-Number & 50 Agents Mapping
- Each WhatsApp Business Phone Number / WABA Line ID maps directly to a specific Bitrix Open Line ID (Line 1 to Line 50).
- Bitrix Open Lines routing ensures agents assigned to Line $N$ only see conversations belonging to Line $N$.
- Bitrix Supervisors receive global access to monitor, audit, and join any conversation across all 50 lines.

### B. 24-Hour Session Window Enforcement
- When a client sends a message, `last_client_msg_ts` is logged in SQLite (`client_sessions` table).
- **Within 24 Hours**: Freeform text, images, voice notes, documents, and videos flow bi-directionally between Bitrix Chat UI and WhatsApp.
- **Outside 24 Hours**: Freeform outgoing messages from Bitrix Chat UI are intercepted. A warning is returned to the agent instructing them to send a Meta Approved Template using the Template Sender Widget.

### C. Meta Approved Template Sender Widget
- Embedded in Bitrix CRM as a Placement / Custom Application.
- Fetches live approved templates (`GET /api/v1/templates`).
- Renders dynamic form fields for body variables (`{{1}}`, `{{2}}`) and header media URLs.
- Sends template via `POST /api/v1/templates/send`, which touches the client session in SQLite and opens/refreshes the 24-hour chat window.

---

## 3. Local Data Model (SQLite)

- **`client_sessions`**: `client_phone (PK)`, `phone_number_id`, `line_id`, `last_client_msg_ts`, `created_at`, `updated_at`
- **`line_mappings`**: `phone_number_id (PK)`, `line_id`, `label`, `updated_at`
- **`message_logs`**: `id (PK)`, `msg_id`, `client_phone`, `phone_number_id`, `line_id`, `direction`, `msg_type`, `content`, `status`, `timestamp`
