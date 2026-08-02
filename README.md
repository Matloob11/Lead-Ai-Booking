# A7 WhatsApp Agent Inbox

A WhatsApp inbox for A7 Group Real Estate, embedded in Bitrix24 and backed by the
alots.io (WBBOX) gateway.

Each agent owns a WhatsApp number and works every chat that arrives on it. An
admin sees all numbers and can hand any conversation to another agent without the
history moving. Conversations live here permanently — the gateway's own agent UI
is not used, so nothing depends on their retention.

Meta closes the free-form window 24 hours after a customer's last message. The
panel tracks that window per conversation: while it is open agents type freely,
and once it lapses the composer is replaced by that number's approved templates,
which reopen the window when sent.

## Layout

```
backend/     Django + DRF + Channels + Celery — API, webhook receiver, gateway client
frontend/    The panel UI rendered inside the Bitrix placement iframe
deploy/      Dockerfile, compose stack, environment template
reference/   Superseded prototypes and notes, kept for context only
```

`reference/` is not built or deployed. The pre-rebuild tree, including the
`vaestvita/thoth` fork this repository started from, is preserved on the
`archive/thoth-base` branch.

## Running locally

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp ../deploy/.env.example .env      # then fill in ALOTS_API_KEY etc.
python manage.py migrate
python manage.py runserver
```

## Deployment

The stack runs on the Hostinger VPS behind nginx at
`https://wa.srv1802669.hstgr.cloud`, which proxies to the app on
`127.0.0.1:8100` and permits framing only from the Bitrix portal origin.

Note that the VPS also hosts unrelated services (Frappe, n8n, pearlzshop), so the
stack is Docker-isolated with its own Postgres and Redis.
