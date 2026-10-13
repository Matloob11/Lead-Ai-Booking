# A7 projects in this repo

Live code + secrets were pulled from the two servers (2026-09-29).
Secrets stay on disk for your work; they are gitignored — do not commit them.

## 1) Official WhatsApp (Hostinger VPS)

| Local folder | Live on server | What it is |
|--------------|----------------|------------|
| `backend/` | Docker image `a7wa-web` (`/app`) + build context `/opt/a7-wa/backend` | Django API (inbox, templates, campaigns, CRM link) |
| `bitrix/public/` | `/opt/a7-wa/panel/` | Agent panel (iframe UI) |
| `deploy/` | `/opt/a7-wa/deploy/` | Docker Compose, nginx, **`.env`** |
| `agent-reports/` | `/opt/a7-wa/agent-reports/` | Daily agent PDF reports |

**Secrets (Official):**

- `deploy/.env` — main API / DB / Redis / Alots / Meta
- `deploy/.env.alots_ui` + `deploy/alots.ui.cookie` — Alots panel session
- `agent-reports/.env`
- Copies also in `files/secrets/official-hostinger/` and `files/secrets/agent-reports/`

**SSH:** `root@187.127.123.235` key `~/.ssh/id_ed25519_hostinger`

---

## 2) Bitrix CRM custom (AWS Lightsail)

| Local folder | Live on server | What it is |
|--------------|----------------|------------|
| `ops/bitrix-aws/` | helpers + flat copies of `a7_*` | Deploy scripts + working copies |
| `ops/bitrix-aws/live/www/` | `/home/bitrix/www/` a7 files | Exact live tree (tools / js / css / php_interface / local) |
| `ops/bitrix-aws/live/nginx/` | `/etc/nginx/...` | Rate-limit / org / recordings conf |
| `ops/bitrix-aws/live/systemd/` | `/etc/systemd/system/a7-*` | Timers/services (lead-shift, 3cx, …) |

Examples of work here: team assign, phone mask, auto timeman, lead WA, renewals WA, call intelligence, attendance, HR CV stage, 3CX click-to-call.

**Secrets (Bitrix):**

- `ops/bitrix-aws/live/www/bitrix/php_interface/a7_call_intelligence.env`
- `ops/bitrix-aws/live/secrets/tenancy.env`
- `ops/bitrix-aws/live/secrets/a7-3cx-worker.env`
- `ops/bitrix-aws/live/www/upload/a7_3cx_click_to_call_config.json`
- Copies also in `files/secrets/bitrix-aws/`

**SSH:** `ec2-user@13.203.81.218` key `~/.ssh/id_ed25519` (not `centos`)

---

## 3) Legacy QR / OpenWA (not product — env only kept)

Code removed from this repo. Envs only, for reference:

- `files/secrets/legacy-qr/openwa.env`
- `files/secrets/legacy-qr/wa-qr.env`

Stacks on Hostinger were already stopped earlier; data may still sit under `/opt/a7-wa/wa-qr` and `/opt/openwa-trial`.

---

## Other folders

| Folder | Role |
|--------|------|
| `ops/wa.sh` | Allowed Hostinger ops script |
| `ops/catalog/` | Official template/catalog helpers |
| `files/briefs/` | PDFs (WA number lists, etc.) |
| `files/secrets/` | All pulled secrets in one place |
| `handoff/` | Separate Bitrix CRM access tooling |
| `docs/` | Specs / plans |

---

## How to know which project you are in

- Changing chats / templates / campaigns / panel → **Official** (`backend` + `bitrix` + `deploy`)
- Changing Bitrix lead boards, phone mask, assign-to-team, timeman → **Bitrix AWS** (`ops/bitrix-aws`)
- Agent PDF reports UI → **agent-reports**
