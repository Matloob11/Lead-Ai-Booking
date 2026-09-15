# Agent Daily Reports — Design

**Date:** 2026-08-21  
**Status:** Approved to implement (user: Sales/TS only; Hostinger; Bitrix iframe; auto 18:00 + on-demand)  
**Repo location:** `agent-reports/` (separate from WhatsApp inbox)

## Problem

Managers need a clear daily view of what each **Sales / TS** Bitrix agent did: leads they own, work on those leads, check-in, calls, talk time, tasks — so idle agents can be followed up. Reports must be stored, browsable in a Bitrix sidebar iframe, and auto-sent on Bitrix Messenger at **18:00 Dubai time** to a fixed recipient list.

## Goals

1. Per-agent daily progress PDF (English UI/copy).
2. History saved and selectable in an “Agent Report” app (sidebar like WhatsApp panel).
3. Auto send at 18:00 Asia/Dubai to: Amna Khan (HR), Admin Abdul Malik, Matloob, Abdul Sattar Mughal.
4. On-demand generate from UI.
5. Data from Bitrix only via dedicated webhook (plus OpenAI for narrative); Hostinger hosted; iframe from CRM.

## Non-goals (v1)

- WhatsApp Official / OpenWA data.
- Direct 3CX API in v1 (use Bitrix `telephony` / voximplant stats already on CRM). Can add 3CX later.
- Editing Bitrix leads from this app.
- Mobile-native app.

## Agents in scope

Bitrix users who are **active** and belong to **Sales / TS** departments (config allowlist of department IDs, recursive children resolved at runtime):

| Area | Dept IDs (initial) |
|---|---|
| Sales Department tree | 60, 61, 62, 63, 65, 66, 67, 68 |
| Re-Sale / TS desks | 41, 43, 45, 46, 52, 54 |

~46 users matched in a live probe (2026-08-21). Config can be edited without code change.

**Lead ownership:** `ASSIGNED_BY_ID` / responsible person on:

- Classic CRM **Leads** (Kanban)
- **Owner Data** SPA (`entityTypeId` **1042**)

Both count toward that agent’s book and today’s activity.

## Recipients (Messenger)

| Bitrix user ID | Name |
|---|---|
| 1 | Admin Abdul Malik |
| 32 | Abdul Sattar Mughal |
| 2311 | Matloob Ul Hassnain Developer |
| 2319 | Amna Khan (HR) |

## Approaches considered

| | Approach | Pros | Cons |
|---|---|---|---|
| **A (chosen)** | New `agent-reports/` service on Hostinger: FastAPI + Postgres + Redis/beat, static panel iframe | Clear isolation from WA; same ops style; small surface | New compose stack to maintain |
| B | Django app inside existing `a7-wa` compose | Shared infra | Couples releases; user asked WA-separate |
| C | n8n-only + Drive PDFs | Fast prototype | Weak history UI, hard iframe product |

**Recommendation:** A.

## Architecture

```
Bitrix left menu "Agent Report"
        │ iframe
        ▼
Hostinger nginx → agent-reports panel (static ES modules)
        │ API
        ▼
FastAPI (web) + worker/beat
        │
        ├─ Bitrix REST (AGENT_REPORT_BITRIX_WEBHOOK)
        ├─ OpenAI (narrative sections in PDF)
        └─ Postgres (report runs, per-agent snapshots, PDF paths)
```

### Daily job (18:00 Asia/Dubai)

1. Resolve Sales/TS user IDs from departments.
2. For each agent, collect day metrics (Dubai calendar day).
3. Build structured JSON snapshot → OpenAI short English summary (facts only; numbers from us).
4. Render PDF → store on disk / DB path.
5. Upload PDF to Bitrix Disk → `im.notify` / file message to each recipient (one digest message listing agents + links, or one PDF per agent — **v1: one ZIP or multi-file digest + “open app for history”**).
6. Mark run `completed` in DB for History UI.

### On-demand

Same pipeline for one agent or all, date default = today; appears in History.

## Report contents (v1)

Per agent, for the Dubai day:

- Check-in / check-out / worked (timeman)
- Lead book: total open Leads + Owner Data assigned
- New assignments today
- Stage moves / timeline comments authored today
- Tasks completed / overdue touch
- Calls: count, total talk minutes (telephony)
- AI paragraph: “what they focused on / risk of idle” grounded in the numbers

## UI (panel)

- Left sidebar: Agents | History | Settings (dept IDs read-only for non-dev)
- Agents: list Sales/TS → Generate today / pick date
- History: past runs, open PDF, filter by agent/date
- English only; build DOM nodes (no `innerHTML` with Bitrix text)

## Auth

Bitrix local app / placement: trust Bitrix iframe session (BX24 or signed placement) for v1; restrict UI actions to users in an admin allowlist (same four + optional WA admins). API rejects unauthenticated calls outside Bitrix embed.

## Config (env)

- `AGENT_REPORT_BITRIX_WEBHOOK`
- `OPENAI_API_KEY` / `OPENAI_MODEL`
- `AGENT_REPORT_DEPT_IDS`
- `AGENT_REPORT_MESSENGER_USER_IDS=1,32,2311,2319`
- `AGENT_REPORT_TZ=Asia/Dubai`
- `AGENT_REPORT_CRON=0 18 * * *`

## Risks

- Timeman / telephony empty for some agents → show “No data” not zero falsely.
- Large agent count → job must batch; 18:00 run may take several minutes.
- Messenger file size limits → prefer Disk link in notify if PDF large.

## Success criteria

1. 18:00 Dubai auto run creates History rows + Messenger notify to four people.
2. Iframe lists agents and can regenerate on demand.
3. PDF numbers match Bitrix spot-checks for one agent for one day.
4. Non-Sales departments never appear unless dept config changed.
