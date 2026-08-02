# Doc 40 — Frontend Web App

> One **web app** (browser, real-time, no page refresh), two experiences by role: the
> **Agent Workspace** and the **Manager/Admin Dashboard**. Media-capable. No WhatsApp key ever
> lives here — it only talks to our backend.
> Related: [20 Backend](20-backend-architecture.md) · [12 Window & Templates](12-window-and-templates.md) · [11 Multi-number](11-multi-number-management.md)

---

## 1. Tech stack

| Concern | Choice |
|---------|--------|
| Framework | **React** (Vite) + TypeScript |
| Styling | **Tailwind CSS** (brand: navy & gold) |
| Realtime | **Socket.IO client** |
| Data fetching | **TanStack Query** (REST + cache) |
| State | React Query + light local state (Zustand if needed) |
| Routing | React Router with role guards |
| Forms | React Hook Form + Zod |
| Auth | JWT in memory + refresh cookie |

> One codebase, responsive. Managers use it on a desktop; agents can use it on a phone browser
> too (since we chose web over a native app). PWA + web-push optional for phone alerts.

---

## 2. Roles → what they see

| Role | Landing | Scope |
|------|---------|-------|
| **Agent** | Agent Workspace | Only their own assigned chats |
| **Manager** | Dashboard | Their team's chats + alerts + stats |
| **Admin/CEO** | Dashboard (full) | Everything + admin panels |

Route guards read the JWT `role`; **the server also enforces scope** — the client never sees
data it isn't allowed to ([Doc 20](20-backend-architecture.md) §6).

---

## 3. Agent Workspace

Layout: **left = chat list**, **center = chat window**, **right = customer card**.

### 3.1 Chat list (left)
- Only this agent's customers, **newest activity first**.
- Each row: name/number, last message preview, time, **unread badge**, and flag chips:
  🔴 serious · ⚠️ competitor · 👥 duplicate.
- Window indicator dot: 🟢 open / ⚪ closed.
- Live: new message bumps the chat to top via `message:new`.

### 3.2 Chat window (center)
- Full conversation, bubbles (inbound left / outbound right).
- **Media rendering:** images inline, PDFs/docs as a file card, voice notes as an audio player, video as a player.
- **Status ticks** on outbound: queued → sent ✓ → delivered ✓✓ → read ✓✓(blue); failed = red with reason.
- **Window banner:**
  - 🟢 Open → free-text box + attach button enabled; optional "closes in 3h 12m".
  - ⚪ Closed → text box **disabled**; **template menu** shown instead ([Doc 12](12-window-and-templates.md)).
- **Competitor banner:** if `is_competitor_agent` → a bold red bar: **"THIS IS A COMPETITOR AGENT — protect owner details."**
- **Duplicate banner:** if `duplicate_flag` → amber bar noting the client is talking to another agent.

### 3.3 Template menu (closed window)
- One-tap list of **approved** templates ([Doc 12](12-window-and-templates.md)).
- Shows a preview with the customer's name pre-filled.
- Sending is one click → optimistic bubble → real status via callback.

### 3.4 Customer card (right)
- Name, community interest, budget, consent state.
- **AI panel:** sentiment, seriousness score (0–100), lead status (Hot/Warm/Cold), intent.
- **Bitrix link** (opens the contact in the CRM).
- Auto-flags on this contact.

### 3.5 Composer
- Text input, emoji, **attach** (image/pdf/audio/video → uploads to backend, [Doc 10](10-whatsapp-cloud-api.md) §6.2).
- Disabled state when window closed (with a clear hint to use a template).
- Enter to send; optimistic append.

### 3.6 Notifications
- In-app toast + unread counts on new customer messages.
- Optional **web push** (PWA) so agents on a phone browser get alerts with the tab closed.

---

## 4. Manager / Admin Dashboard

### 4.1 Live chats
- Real-time grid/list of every (team's) agent's active conversations.
- Click through to a read-only (or intervene-capable) chat view.

### 4.2 Hot Leads panel
- All customers currently above the hot threshold, across agents — name, agent, community, score.
- Click → jump to the chat.

### 4.3 Alerts feed
- Live stream: competitor detected, duplicate detected, agent behaviour flag, number-health.
- Mark-as-seen; filter by type.

### 4.4 Agent scoreboard
- Per agent: messages sent, avg response time, hot leads handled, deals moved (from Bitrix).
- Sortable; date range.

### 4.5 Number health panel  *(multi-number)*
- Per number: label, display number, quality 🟢🟡🔴, tier, today's usage vs cap, status.
- **Pause / resume** outreach per number ([Doc 11](11-multi-number-management.md)).

### 4.6 Search
- Any customer / number → full history instantly (uses server search, trigram index).

### 4.7 Admin panels (admin only)
- **Numbers:** add/edit/assign/pause, set warm-up.
- **Templates:** create/edit variants, submit to Meta, track status, enable/disable.
- **Competitor DB:** CSV upload, whitelist/remove ([Doc 52](52-competitor-detection.md)).
- **Agents:** add/remove, assign community/team, roles.
- **Reassign:** move a customer from one agent to another (one click).
- **Outreach:** create/pause campaigns, view consent-skip reasons ([Doc 13](13-consent-and-ban-safety.md)).
- **Settings:** hot-lead threshold, outreach caps, pacing.
- **Exports:** conversations / reports (CSV).
- **Cost report:** free vs paid messages, per number, estimated spend ([Doc 53](53-cost-control.md)).

---

## 5. Real-time integration (Socket.IO)

On login the client opens a socket authenticated with the JWT and joins server-side rooms by
role. It listens for:

| Event | UI effect |
|-------|-----------|
| `message:new` | append bubble / bump chat / unread badge / toast |
| `message:status` | update tick state on the bubble |
| `lead:scored` | update AI panel + hot-leads list |
| `alert:duplicate` / `alert:competitor` / `alert:behaviour` | banner + alerts feed |
| `number:health` | update number-health panel |

Reconnect strategy: on reconnect, refetch the open chat + list via REST to fill any gap.

---

## 6. Screen inventory

| Screen | Role |
|--------|------|
| Login | all |
| Agent Workspace (list + chat + card) | agent (+ managers can open) |
| Dashboard home (live + hot leads + alerts) | manager/admin |
| Agent scoreboard | manager/admin |
| Number health | manager/admin |
| Search results | manager/admin |
| Admin: numbers / templates / competitors / agents / outreach / settings / exports / cost | admin |

---

## 7. UX rules (from the spec — adoption is everything)

- **One tap to re-open** a closed chat. No friction, ever.
- **No dead ends:** closed window never leaves the agent stuck — template menu is right there.
- **Least access:** an agent literally cannot navigate to another agent's chats.
- **Fast + live:** everything updates without refresh; optimistic sends feel instant.
- **Brand:** navy & gold, clean, chat-app-familiar so agents actually use it.

---

## 8. Testing checklist

- [ ] Agent sees only their chats; cannot load another agent's (UI + API blocked).
- [ ] New inbound appears live with unread badge + toast.
- [ ] Outbound shows optimistic bubble, then real sent/delivered/read ticks.
- [ ] Failed send shows red + reason.
- [ ] Closed window disables text box and shows template menu; one tap re-opens.
- [ ] Competitor/duplicate banners render on flagged chats.
- [ ] Media (image/pdf/voice/video) renders inbound and can be sent outbound.
- [ ] Manager dashboard live-updates hot leads, alerts, number health.
- [ ] Admin can manage numbers/templates/competitors/agents and reassign a customer.
- [ ] Reconnect after network drop refetches without losing messages.

---

*Next: [Doc 50 — AI Intelligence (OpenAI)](50-ai-intelligence.md).*
