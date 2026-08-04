# A7 WhatsApp Inbox

A WhatsApp agent inbox for A7 Group Real Estate, embedded in their self-hosted
Bitrix24 as a left-menu iframe, talking to Meta through the alots.io (WBBOX)
gateway. Django + DRF + Channels + Celery behind Postgres and Redis; the panel is
plain ES modules served as static files.

## Deploying

There is no build step and no CI. The live system is a Hostinger VPS.

```
ssh -i "$HOME/.ssh/hostinger_codex" -o BatchMode=yes root@187.127.123.235
```

**Backend** — `/opt/a7-wa/backend` on the host is bind-mounted to `/app` in
`web`, `worker` and `beat`. Write to the *host* path and restart:

```bash
tar -cf - -C backend apps/... | ssh … 'tar -xf - -C /opt/a7-wa/backend --overwrite \
  && chown -R 10001:10001 /opt/a7-wa/backend'
ssh … 'cd /opt/a7-wa/deploy && docker compose restart web worker beat'
```

Do **not** deploy with `docker compose cp` into a container. It writes inside one
container only, the container runs as uid 10001 and cannot overwrite files the
mount owns, and anything it does write is lost when the container is recreated.
Copying into `web` while `worker` and `beat` read the mount is how the three
services end up running three different versions of the code.

**Panel** — `bitrix/public/` → `/opt/a7-wa/panel/`, owned by `www-data`, then
`systemctl reload nginx`. `bitrix/deploy/deploy-panel.sh` does this with rsync
where rsync exists; a `tar | ssh` pipe is the fallback.

After any deploy, confirm what is live rather than assuming — compare `md5sum`
against `https://wa.srv1802669.hstgr.cloud/app/assets/<file>`, and check
`docker compose ps` for a service stuck in `Restarting`.

## Migrations

Generated inside the container, so they must be copied back into this repo *and*
left on the server's disk. A migration that exists in one place only has bitten
this project twice: Django regenerates it, and the regenerated copy tries to
build a model over its own live table.

Always finish with `manage.py makemigrations --check --dry-run` reporting
"No changes detected", and `showmigrations` agreeing with `django_migrations`.

## What the gateway will and will not do

`POST /{phone_number_id}/messages` is documented as a raw Meta pass-through and
is really an allowlist. Verified by probing every type:

- **forwarded** — text, image, video, audio, document, sticker, location,
  template, interactive
- **rejected** — read receipts (and the typing indicator that rides on them),
  reaction, contacts, order, button, system

So blue ticks, "typing…" and *sending* reactions cannot work here however correct
the payload is. Inbound reactions and read receipts arrive fine. The
`GATEWAY_SUPPORTS_*` flags in settings exist so the panel neither spends a call
on a send that cannot succeed nor offers a button that will never work.

Two more things the docs get wrong: location coordinates must be JSON **numbers**
(strings return "Invalid JSON format"), and `GET /{version}/{id}` for media is
broken for this account — inbound media is fetched from the `filelink` the
webhook already carries.

Template creation *does* reach Meta: `POST /{waba_id}/message_templates` returns
Meta's own validation errors, so the route is live.

## Rules the UI has to mirror

- An agent sees **every** chat on the numbers they cover. `assigned_agent` is
  ownership for transfers, never a list filter.
- One conversation per (our number, customer) — enforced by
  `unique_conversation_per_number`. Messaging the same customer from a different
  number opens a second thread, deliberately.
- The 24-hour free-form window opens **only** on an inbound message. Sending a
  template does not open it; it earns the right to be replied to. Getting this
  wrong hands the agent Meta's error 131049 after the send has already failed.
- 163 of the ~260 approved templates are MARKETING and share Meta's per-customer
  daily cap. A MARKETING send coming back undelivered is usually that cap, not a
  bug.

## House style

- **English only** in anything an agent can see. The panel was Roman Urdu once
  and was converted; do not reintroduce it. Conversation with the user in this
  repo is Roman Urdu, the product is not.
- Plain ES modules, no framework, no bundler, no CDN. `core/dom.js` has `el`,
  `clear`, `debounce`, `modal`, `stamp`, `untilText`, `formatBytes`.
- `icon(name)` returns `null` for a name it does not hold and `el()` drops null
  children — a missing icon is an empty button, not a fallback glyph. Add the
  icon to `core/icons.js`.
- Each screen owns a CSS file and a class prefix (`tplc-`, `na-`, `wa-x-`), and
  `index.html` links it.
- Never `innerHTML` with a message body, a template body, or anything an agent
  typed. Build nodes.

## Files are shared with other agents

Two other AI sessions work this repo at the same time (one on Antigravity).
Before editing a frontend module, check `git log` and `git status` — if it has
uncommitted changes, it is probably mid-edit somewhere else. Prefer adding a new
module over widening an existing one, and say in the reply which shared files
were touched so the user can pass it on.

## Talking to the server: `ops/wa.sh`

Everything routine on the live host goes through this script, and it is the only
thing on the allowlist that reaches the server:

```
ops/wa.sh ps                         both stacks, container states
ops/wa.sh logs qr app 200            container logs
ops/wa.sh sql qr "SELECT …"          read-only query
ops/wa.sh sum /opt/a7-wa/panel/x.js  checksum of a deployed file
ops/wa.sh get /app/assets/x.js       fetch from the public site
ops/wa.sh push local remote          copy one file
ops/wa.sh build qr app               rebuild an image
ops/wa.sh restart qr app             restart services
ops/wa.sh django-check               makemigrations --check + showmigrations
```

`ssh`, `scp`, `curl`, `tar`, `find` and `ls` are **not** on the allowlist and
must not be added. Each takes an argument that runs something else — `find
-exec`, `tar --to-command`, `curl -o` writing wherever it likes, `ssh host
<anything>` — so allowing one approves every command it can reach, which is all
of them. That matters here more than in most repos: this codebase reads customer
messages, webhook bodies, template text and uploaded filenames into the model's
context, and every word of it was written by somebody outside the company.

The script is the narrow thing that can be allowed instead. Stack names resolve
against a list of two, service names must look like service names, paths must
sit under `/opt/a7-wa`, and queries run inside a transaction Postgres itself
marks `READ ONLY` — so a write is refused by the database rather than by a
regex that thought the query looked harmless. Adding a subcommand is a
deliberate act; widening `ssh` would have been an accident waiting to be made.

Anything the script does not cover still runs as a plain command and still gets
looked at first. That is the boundary — not the deny list, which only matches
commands spelled locally and never sees the same command inside `ssh …`.

Use Glob, Grep and Read instead of `ls`/`find`/`cat` — they are faster, they do
not need approval, and they cannot be turned into something else.

## Verifying

The user asks for deep verification because features have shipped looking
finished and not working. Reaching an endpoint is not evidence it does its job.
For anything user-facing, check the whole path: that the file is served, that the
link resolves, that the permission gate actually refuses, that the scheduled task
actually ran. Test on the live server against real data — the test client inside
the `web` container, forced-logged-in as a real agent, is the fastest way.

Say plainly what was tested and what was not.
