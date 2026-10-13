# A7 WhatsApp Agent Inbox

WhatsApp inbox for A7 Group Real Estate. Agents work inside a Bitrix24 left-menu iframe. Traffic goes through the alots.io (WBBOX) gateway to Meta Cloud API (Official WhatsApp only).

Each agent sees every chat on the WhatsApp numbers they cover. `assigned_agent` is ownership for transfers, not a list filter. One conversation exists per (our number, customer). Messaging the same customer from a different number opens a second thread on purpose.

Conversations stay in this product. The gateway’s own agent UI is not used, so retention does not depend on theirs.

## How the 24-hour window works

Meta opens the free-form window only on an inbound customer message. Sending a template does **not** open it; it earns the right to be replied to. The panel tracks that window per conversation: while it is open agents type freely; once it lapses the composer is replaced by that number’s approved templates.

A large share of approved templates are MARKETING and share Meta’s per-customer daily cap. An undelivered MARKETING send is usually that cap, not a panel bug.

## What the gateway will and will not send

`POST /{phone_number_id}/messages` is documented as a raw Meta pass-through. In practice it is an allowlist.

**Forwarded:** text, image, video, audio, document, sticker, location, template, interactive.

**Rejected:** read receipts (and the typing indicator that rides on them), outbound reactions, contacts, order, button, system.

Blue ticks, “typing…”, and *sending* reactions cannot work here however correct the payload is. Inbound reactions and read receipts arrive fine. `GATEWAY_SUPPORTS_*` in Django settings exists so the panel does not offer a button that can never succeed.

Two more documentation traps: location coordinates must be JSON **numbers** (strings return “Invalid JSON format”), and `GET /{version}/{id}` for media is broken for this account — inbound media is fetched from the `filelink` the webhook already carries.

Template creation *does* reach Meta: `POST /{waba_id}/message_templates` returns Meta’s own validation errors.

Official Meta Cloud limits still apply (about 16 MB video, 100 MB other files). Larger videos are sent as documents.

## Layout

Live product code stays in these folders (do not dump spreadsheets or screenshots here):

```text
backend/          Official API — Django (live from Hostinger web container)
bitrix/public/      Agent panel (live from /opt/a7-wa/panel)
deploy/             Official Compose + nginx + .env (secrets gitignored)
ops/bitrix-aws/     Bitrix CRM custom (AWS live under live/)
agent-reports/      Daily agent PDF reports
files/secrets/      All pulled .env / cookies (local only)
handoff/            Bitrix CRM access scripts
docs/               Specs and plans
files/              Briefs / working files
```

See **PROJECTS.md** for which folder = which server.

Panel house rules: English only in anything an agent can see; no `innerHTML` with a message body, template body, or anything an agent typed — build DOM nodes. Each screen owns a CSS file and a class prefix.

## Requirements

- Python 3.12+ for the Official API
- Docker + Compose for the live stack
- Postgres and Redis (Compose provides them)
- An alots.io / WBBOX account and Meta Cloud credentials
- A Bitrix24 portal origin for iframe framing

## Run the Official API locally

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp ../deploy/.env.example .env
python manage.py migrate
python manage.py runserver
```

Fill `ALOTS_API_KEY`, database, Redis, and Bitrix values in `.env`. Root `.env.example` is a smaller Bitrix/OpenAI helper set; the Compose file reads `deploy/.env.example`.

Never commit `.env`, cookies, SQLite dumps, or campaign/CRM exports. Those paths are in `.gitignore`.

## Deployment

There is no CI. The live Official stack is a Hostinger VPS. Backend code is **baked into the image**, not mounted. The only volumes are `../media` and `../static`. Writing files under `/opt/a7-wa/backend` changes nothing until an image is built from that tree.

Typical flow:

```bash
ops/wa.sh push backend/apps/x/y.py /opt/a7-wa/backend/apps/x/y.py
cd /opt/a7-wa/deploy && docker compose build && docker compose up -d
```

Build with **no service argument**, and `up -d`, not `restart`:

- `web`, `worker`, and `beat` build separately. `build web` leaves the other two on old images. Webhook processing happens in `worker`; everything you reach by hand answers from `web`.
- `env_file:` is read when a container is *created*. A new environment variable is invisible to `restart`.

Panel: `bitrix/public/` → `/opt/a7-wa/panel/`, owned by `www-data`, then `systemctl reload nginx`. `bitrix/deploy/deploy-panel.sh` does this with rsync where rsync exists.

After any deploy, confirm what is live — compare checksums against `https://wa.srv1802669.hstgr.cloud/app/assets/<file>`, and check `docker compose ps` for a service stuck in `Restarting`.

Routine host work goes through `ops/wa.sh` (`ps`, `logs`, `sql`, `sum`, `get`, `push`, `build`, `restart`, `django-check`). Migrations generated inside the container must be copied back into this repo *and* left on the server disk.

The VPS also hosts unrelated services, so this stack is Docker-isolated with its own Postgres and Redis. nginx proxies the Official app on `127.0.0.1:8100` and permits framing only from the Bitrix portal origin.

## Tests and checks

```bash
# inside the web container, or locally after migrate
python manage.py makemigrations --check --dry-run
python manage.py showmigrations
```

Reaching an endpoint is not evidence it does its job. For anything user-facing, check that the file is served, the permission gate refuses strangers, and the scheduled task actually ran.

## License

Private repository. Internal to A7 Group.
