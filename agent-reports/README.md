# Agent Daily Reports

Separate Hostinger app for **Sales / TS** Bitrix agent daily PDFs.

- Spec: `docs/superpowers/specs/2026-08-21-agent-daily-reports-design.md`
- Plan: `docs/superpowers/plans/2026-08-21-agent-daily-reports.md`

## What it does

1. Resolves Sales/TS agents from Bitrix departments.
2. Collects check-in, leads (Kanban + Owner Data), tasks, calls for the Dubai day.
3. Builds PDF (+ OpenAI narrative grounded in numbers).
4. Saves history; Bitrix left-menu iframe UI for on-demand + history.
5. Auto Messenger digest at **18:00 Asia/Dubai** (Celery beat) to Abdul Malik, Sattar Mughal, Matloob, Amna Khan.

## Local quick start

```bash
cd agent-reports/backend
python -m venv .venv
pip install -r requirements.txt
# ensure agent-reports/.env has AGENT_REPORT_BITRIX_WEBHOOK + OPENAI_API_KEY
uvicorn app.main:app --reload --port 8090
```

- Health: `http://127.0.0.1:8090/health`
- Panel: open `agent-reports/panel/index.html` (set `localStorage.ar_api_base` if API not on 8090)

### APIs

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/agents` | Sales/TS list |
| GET | `/api/agents/{id}/day` | Live day snapshot |
| POST | `/api/reports/generate` | `{ agent_ids?, day?, notify?, upload? }` |
| GET | `/api/reports` | History runs |
| GET | `/api/reports/items/{id}/pdf` | Download PDF |

### Celery (18:00 Dubai)

Needs Redis:

```bash
celery -A app.workers.celery_app.celery_app worker -l info
celery -A app.workers.celery_app.celery_app beat -l info
```

Or force a full run via API: `POST /api/reports/generate` with `"notify": true`.

## Hostinger deploy

```bash
# on server
cd /opt/a7-agent-reports
# copy agent-reports/ tree + .env
cd deploy && docker compose build && docker compose up -d
```

Wire `deploy/nginx-snippet.conf`, then Bitrix left menu **Agent Report** → iframe to panel URL. Point panel `ar_api_base` to `/agent-reports-api` (or absolute API URL).

## Env

See `.env.example`. Messenger recipients: `1,32,2311,2319`. Depts: Sales tree + Re-Sale/TS.
