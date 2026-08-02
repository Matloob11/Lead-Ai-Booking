# A7 Bitrix24 WhatsApp Business API (WABA) Integration Architecture

## 1. Executive Summary
This document defines the complete technical architecture for the in-house **Meta WhatsApp Business API (WABA) + Bitrix24 Open Channels Integration Hub**. 
The system connects Meta Cloud WABA directly to Bitrix24 Contact Center without third-party monthly SaaS subscriptions (360dialog, Twilio, Wazzup).

---

## 2. Core Architectural Pillars

```
                     ┌─────────────────────────────────────────┐
                     │         Meta Cloud WABA Webhooks        │
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    A7 WABA Integration Hub (Django Core)                    │
│                                                                              │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌───────────────────┐  │
│  │   Multi-Number Router │  │ 24h Session Manager  │  │  Bitrix Connector │  │
│  │    (50 Agent Phone)   │  │ (Window & Templates) │  │  (imconnector API)│  │
│  └───────────────────────┘  └──────────────────────┘  └───────────────────┘  │
└─────────────────────────────────────────┬────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │ Bitrix24 Open Channels (Agent Desk UI)  │
                     └─────────────────────────────────────────┘
```

### Pillar A: Multi-Number Agent Routing (50 Agents)
- Maps each of the 50 agents or departments to their specific WABA Phone Number / Phone Number ID.
- Automatically routes incoming customer messages on Phone X to Bitrix Open Channel Line X.
- Outbound agent replies are automatically sent from the exact same phone number.

### Pillar B: 24-Hour Session Window Management
- **In-Session (0 - 24 Hours)**: Free-form text, images, voice notes, PDFs, and documents allowed.
- **Out-of-Session (> 24 Hours)**: Free-form text blocked by Meta. System automatically restricts agent to sending Meta-Approved HSM Templates with dynamic variables (`{{1}}`, `{{2}}`, etc.).
- **Automatic Window Reset**: Whenever a customer sends an inbound message, the 24-hour timer resets automatically.

### Pillar C: Native Bitrix24 Open Channels (`imconnector`) Integration
- Registers an in-house Bitrix24 Local App using native REST API scopes: `imconnector`, `crm`, `imopenlines`, `contact_center`.
- Inbound messages create or update Bitrix CRM Leads/Contacts and open live agent chats inside Bitrix Chat Widget.
- Agent replies inside Bitrix Chat trigger `imconnector` webhooks that send WABA messages via Meta API.

---

## 3. Component Architecture

### 1. Backend Engine (`separator.waba`, `separator.bitrix`)
- **Meta Webhook Handler**: Receives incoming customer messages, status callbacks (`sent`, `delivered`, `read`), and payload verification (`hub.verify_token`, SHA-256 HMAC signature).
- **Bitrix Webhook Handler**: Listens for Bitrix agent outgoing chat events (`ONIMCONNECTORMESSAGEADD`).
- **Session Tracker Service**: Maintains active 24h conversation windows in DB.

### 2. Frontend Widget (`a7_waba_widget.html`)
- Embedded inside Bitrix CRM / Open Channels side panel.
- Displays WABA 24h window countdown timer.
- Allows agents to pick Meta-Approved Templates, fill parameters (`{{1}}`, `{{2}}`), preview messages, and trigger outbound template sends when outside the 24h session window.

---

## 4. Database Schema Overview

1. `waba_channel`: Stores Phone Number IDs, WABA Account IDs, and mapped Bitrix Line IDs.
2. `waba_session`: Stores Customer Phone, Agent Line ID, Last Customer Message Timestamp, and Session Active Status (True/False).
3. `waba_template`: Stores Meta-Approved Templates, language, header/body/footer content, and variable placeholders (`{{1}}`, `{{2}}`).
4. `waba_message_log`: Stores Message ID, Direction (Inbound/Outbound), Type (Text/Template/Media), Bitrix Chat ID, and Meta Delivery Status.

---

## 5. Local Development & Verification Plan
1. **Local Setup**: Run Django dev server on `http://127.0.0.1:8000/admin/`.
2. **Mock Webhook Testing**: Test Meta incoming webhooks and Bitrix outgoing webhooks using mock JSON payloads.
3. **Template UI Verification**: Test template selection, variable substitution, and countdown timers in `a7_waba_widget.html`.
4. **Staging Approval**: Verify 100% functionality locally before deploying to production.
