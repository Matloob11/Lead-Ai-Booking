# 01 - System Overview & Business Vision

## 1. Project Purpose & Objectives
The **A7 Bitrix24 WhatsApp Business API (WABA) Integration System** is an enterprise-grade in-house communications hub. It directly connects the official **Meta Cloud WhatsApp Business API** with **Bitrix24 Contact Center (Open Channels)** without relying on third-party paid middleware services (such as 360dialog, Wazzup, Twilio, or ChatApi).

### Key Business Advantages
- 💵 **Zero Subscription Costs**: Eliminates monthly per-agent or per-line fees charged by third-party connectors.
- 🏢 **Multi-Agent Scale**: Supports 50+ individual sales/support agents with dedicated phone numbers or shared line pools.
- ⚡ **Direct Meta Cloud Connection**: Uses direct Meta Graph API (v19.0+) with lowest possible message delivery latency.
- 🛡️ **Complete Data Sovereignty**: All customer conversations, media attachments, and logs reside on in-house infrastructure.

---

## 2. System Architecture Overview

```
 ┌────────────────────────┐                    ┌────────────────────────┐
 │ Meta Cloud WABA API    │                    │ Bitrix24 Open Channels │
 └───────────┬────────────┘                    └───────────▲────────────┘
             │ Inbound Webhook                             │ Native Chat UI
             ▼                                             │
 ┌─────────────────────────────────────────────────────────┴────────────┐
 │                  A7 WABA Integration Hub (Django)                    │
 │                                                                      │
 │  ┌──────────────────────┐ ┌────────────────────┐ ┌─────────────────┐ │
 │  │ WABA Webhook Handler │ │ 24h Session Manager│ │ Bitrix Connector│ │
 │  └──────────────────────┘ └────────────────────┘ └─────────────────┘ │
 │                                                                      │
 │  ┌──────────────────────┐ ┌────────────────────┐ ┌─────────────────┐ │
 │  │ Multi-Number Router  │ │ HSM Template Sender│ │ Local SQLite/PG │ │
 │  └──────────────────────┘ └────────────────────┘ └─────────────────┘ │
 └──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Functional Capabilities

### A. Dedicated 50-Agent Multi-Number Phone Routing
- Each agent or department is mapped to their unique WABA Phone Number ID / Display Number.
- Inbound messages on Phone Number A route directly to Bitrix Open Channel Line A and assign the lead to Agent A.
- Outbound replies automatically originate from the same Phone Number A.

### B. 24-Hour Session Window & Template Engine
- **Active Window (0 to 24 Hours)**: Free-form text and media messages flow seamlessly.
- **Expired Window (> 24 Hours)**: Free-form text is restricted by Meta. Agents use the embedded Side-Panel UI Widget to pick Meta-Approved HSM Templates with dynamic variables (`{{1}}`, `{{2}}`).
- **Auto-Reset**: Any customer incoming reply instantly resets the 24-hour window timer.

### C. Native Bitrix24 Contact Center Integration
- Uses Bitrix `imconnector` API to embed directly into Bitrix Chat.
- Agents work inside standard Bitrix chat windows without opening external browser tabs.
- Supports message delivery status indicators (Sent, Delivered, Read, Failed).
