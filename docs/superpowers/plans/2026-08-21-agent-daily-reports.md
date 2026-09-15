# Agent Daily Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hostinger-hosted Agent Report app (Bitrix iframe) that builds Sales/TS daily PDFs, stores history, supports on-demand generate, and auto-sends Bitrix Messenger digests at 18:00 Asia/Dubai.

**Architecture:** Isolated `agent-reports/` stack — FastAPI + Postgres + Redis worker/beat + static panel. Bitrix webhook for CRM/users/timeman/telephony/im/disk; OpenAI for narrative only.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Celery + Redis, WeasyPrint or reportlab PDF, plain ES modules panel, Docker Compose on Hostinger.

**Spec:** `docs/superpowers/specs/2026-08-21-agent-daily-reports-design.md`

## Global Constraints

- English-only agent-facing copy.
- Never `innerHTML` with Bitrix/user text — build DOM nodes.
- Secrets only in env / `.env` (gitignored); use `AGENT_REPORT_*` keys.
- Do not couple deploys to WhatsApp `a7-wa` images; separate compose project.
- Sales/TS = configured department IDs only (initial: 60–68 Sales tree + 41/43/45/46/52/54 Re-Sale related).
- Leads = classic Lead + Owner Data entityTypeId 1042; owner = responsible / ASSIGNED_BY_ID.
- Messenger recipients: 1, 32, 2311, 2319.
- Schedule: `0 18 * * *` Asia/Dubai.

## File map

```
agent-reports/
  README.md
  .env.example
  deploy/docker-compose.yml
  deploy/nginx-snippet.conf
  backend/
    Dockerfile
    requirements.txt
    app/main.py
    app/config.py
    app/db.py
    app/models.py
    app/bitrix/client.py
    app/bitrix/agents.py
    app/bitrix/metrics.py
    app/reports/collect.py
    app/reports/pdf.py
    app/reports/ai_summary.py
    app/reports/deliver.py
    app/api/routes.py
    app/workers/tasks.py
    app/workers/celery_app.py
    tests/
  panel/
    index.html
    assets/app.js
    assets/app.css
    assets/api.js
```

---

### Task 1: Scaffold project + config

**Deliverable:** `agent-reports/` boots locally with health endpoint and env example.

- [ ] Create folder tree above.
- [ ] `config.py`: load `AGENT_REPORT_*`, OpenAI, DB, Redis.
- [ ] FastAPI `/health` → `{"ok": true}`.
- [ ] `.env.example` with webhook placeholder (no real secret).
- [ ] README: Hostinger deploy notes + Bitrix placement iframe URL pattern.

**Verify:** `uvicorn` health 200.

---

### Task 2: Bitrix client + Sales/TS agent resolution

**Deliverable:** List of in-scope agents from live webhook.

- [ ] `bitrix/client.py`: REST helper, pagination.
- [ ] `bitrix/agents.py`: expand dept IDs → active users.
- [ ] Unit test with mocked `user.get` / `department.get`.
- [ ] CLI or `/api/agents` (auth stub) returns count + ids/names.

**Verify:** Against live webhook, count ≈ Sales/TS probe (~40+); no Marketing/HR-only users unless also in Sales depts.

---

### Task 3: Metrics collector (one agent, one Dubai day)

**Deliverable:** JSON snapshot: check-in, leads book, today’s activity, calls, tasks.

- [ ] `metrics.py` / `collect.py`:
  - timeman for user
  - crm.lead.list assigned + activity date filters
  - crm.item.list entityTypeId 1042
  - tasks.task.list
  - voximplant.statistic.get filtered by user/day
- [ ] Normalize to a typed dict / Pydantic model `AgentDaySnapshot`.
- [ ] Test with fixtures (no live Bitrix in CI).

**Verify:** Manual spot-check one known agent vs Bitrix UI for today.

---

### Task 4: PDF + AI summary

**Deliverable:** PDF bytes on disk for one snapshot.

- [ ] `ai_summary.py`: OpenAI call; prompt forbids inventing numbers.
- [ ] `pdf.py`: render English PDF (header, stats table, lead highlights, AI blurb).
- [ ] Store path under `storage/reports/{date}/{user_id}.pdf`.

**Verify:** Open PDF; numbers match snapshot JSON.

---

### Task 5: DB history + API

**Deliverable:** Persist runs; list/get from API.

- [ ] Models: `ReportRun`, `AgentReport` (agent_id, date, status, metrics_json, pdf_path, error).
- [ ] Routes: `GET /api/agents`, `GET /api/reports`, `GET /api/reports/{id}`, `POST /api/reports/generate`.
- [ ] Auth middleware stub → Bitrix placement token later.

**Verify:** Generate → appears in list → PDF downloadable.

---

### Task 6: Messenger delivery

**Deliverable:** After run, four recipients get Bitrix notify with Disk link(s).

- [ ] Upload PDF(s) via `disk`.
- [ ] `im.notify.system.add` (or file message) to user IDs 1, 32, 2311, 2319.
- [ ] Digest text: date, agent count, “open Agent Report for history”.

**Verify:** Test notify to Matloob only first (`AGENT_REPORT_MESSENGER_USER_IDS=2311`), then enable all four.

---

### Task 7: Celery beat 18:00 Dubai + panel UI

**Deliverable:** Scheduled full run; iframe UI usable.

- [ ] Celery task `run_daily_reports`.
- [ ] Beat schedule timezone Asia/Dubai 18:00.
- [ ] Panel: sidebar Agents / History; generate button; history list; PDF open.
- [ ] nginx snippet + Bitrix menu placement instructions in README.

**Verify:** Force-enqueue task; History + Messenger; hard-refresh iframe.

---

### Task 8: Hostinger deploy

**Deliverable:** Live URL for Bitrix iframe.

- [ ] `deploy/docker-compose.yml` (web, worker, beat, postgres, redis).
- [ ] Push code to Hostinger path (e.g. `/opt/a7-agent-reports`).
- [ ] Wire env from server file (not WhatsApp `.env` blindly).
- [ ] Bitrix left menu → iframe URL.
- [ ] Confirm 18:00 run once (or temporary cron test time).

**Verify:** Four recipients receive evening digest; UI history matches.

---

## Done when

- [ ] Spec success criteria all met.
- [ ] `TASKS.md` entry with files + what was / was not verified.
