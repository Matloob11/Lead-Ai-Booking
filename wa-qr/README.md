# wa-qr — a QR-linked WhatsApp channel

A second way into WhatsApp for the A7 inbox: instead of a number registered on
the WhatsApp Business Platform, a phone is linked by scanning a QR code, the way
WhatsApp Web does it. Built on [whatsapp-web.js].

It runs **on its own** — its own container, its own database, its own port. It
does not import anything from `backend/`, and `backend/` does not know it
exists. Attaching the two is a later, deliberate step; see *Joining it up* below.

## Read this before connecting a number

Linking through the web protocol is **against WhatsApp's Terms of Service**.
Meta detects it by behaviour — message volume, timing, patterns no person
produces — and the penalty is a permanent ban of the number, with no warning and
no appeal. Chat history on that number goes with it.

So:

- **Never link one of the 21 numbers already on the WhatsApp Business Platform.**
  Those are verified, they carry ~260 approved templates, and they are the
  business's actual channel. This service refuses them by configuration — see
  `BLOCKED_NUMBERS` in `.env.example`, which is loaded on startup and checked
  before any link.
- Use a separate SIM bought for the purpose.
- Treat any linked number as disposable. Assume it will be banned eventually and
  make sure nothing depends on it.

The official route to a QR-linked number is Meta's own *coexistence* flow, which
links an existing WhatsApp Business App number to the Cloud API with no ban risk.
If that becomes available through the gateway, prefer it and retire this service.

## Shape

```
phone ──QR──► whatsapp-web.js ──► normalise ──► Postgres
                                      │
                                      └──► webhook (later: the Django backend)
```

`src/inbound/normalise.js` is the piece that matters. Every event coming off
whatsapp-web.js is rewritten into **the same JSON the alots.io gateway sends**.
That is deliberate: the Django backend already parses that shape in
`apps/gateway/tasks.py`, so joining the two later means pointing this service's
webhook at `/api/gateway/webhook/alots/` rather than writing a second parser.

## Running it

```bash
cd wa-qr
cp .env.example .env        # then edit it
docker compose up --build
```

Then open `http://127.0.0.1:8300/` and scan the QR with the phone you are
linking. The session survives restarts — the auth data is a volume, not
something to re-scan for every deploy.

## Who may see what

More than one phone can be linked, and each one belongs to somebody. The rules
are the Cloud side's rules, on purpose — `catalog.NumberAssignment` and
`qr_session_agent` are the same idea in two databases:

- An **admin** sees every phone and every conversation.
- An **agent** sees the phones assigned to them, and then **every** conversation
  on those phones — not only the ones they answered. The agent gives that number
  to the customer themselves, and a colleague covering for them is normal.
- An assignment is ownership, not a filter. It decides which *phones* an agent
  can reach at all.
- Removing an agent sets `is_active = false`. Nothing is deleted: who held a
  number in March is the question asked in September.

Agents are not stored here. They live in Django's `accounts_agent`, and
`qr_session_agent.agent_id` carries that id without resolving it — one place
creates an agent, so there is one truth about who exists.

### Identity comes from nginx

This service has no login. nginx authenticates the caller against Django and
states the answer in two headers:

```
X-WA-Agent-Id: 5      accounts_agent.id of the signed-in agent
X-WA-Is-Admin: 1      "1" when that agent has admin rights
```

`proxy_set_header` **must** set both on every proxied request. It replaces
rather than appends, which is the point: nothing downstream can tell a header
nginx wrote from one a browser typed, so if the client's own copy survived, any
agent could send `X-WA-Is-Admin: 1` and become one.

A request to `/api` without them is answered `401`. That is deliberate — the
service cannot tell who is asking, and everything behind it is somebody's
private conversation. Until nginx is wired, the panel loads and its first fetch
returns 401.

### The endpoints that carry it

```
GET  /api/sessions                         each session, plus agents: [{agent_id, role}]
PUT  /api/sessions/:id/agents              {agents: [{agent_id, role}]} — replaces the roster
GET  /api/sessions/:id/agents              the roster alone
GET  /api/conversations?session_id=&agent_id=
GET  /api/conversations/:id/messages
```

`PUT` replaces rather than merges, so the screen sends the state it wants and
never has to work out what changed — the same contract as
`PUT /api/catalog/numbers/{id}/agents/`. `role` is `primary` or `backup`.

Assigning, creating and destroying a phone are admin-only. `agent_id` on the
conversations list is a lens for looking at one agent's work; it can only narrow
what the caller may already see, never widen it.

The list of agents to choose from is Django's:
`GET /api/catalog/agents/`, same origin as the panel, so the admin's own session
authenticates it. This service never fetches it and holds no credential for it.

## Joining it up (later, not now)

1. Add a `channel_type` to `catalog.WabaNumber` — `cloud` or `qr`.
2. Point `WEBHOOK_URL` at the Django webhook and give it the shared token.
3. Sending: `apps/inbox/services.py` picks the client by `channel_type`, so a
   QR number sends through this service's `/api/send` and a Cloud number keeps
   going to alots.

Nothing above needs doing yet. It is written down so the shape stays right.

[whatsapp-web.js]: https://github.com/pedroslopez/whatsapp-web.js
