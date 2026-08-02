# A7 WhatsApp Integration Project Task List & Communication Board

## Project Workspace
- **Local Path**: `C:\Users\Matloob\Desktop\a7-full-whatsapp-system`
- **Local Dev Server**: `http://127.0.0.1:8000/admin/`
- **Superuser Credentials**: `admin@example.com` / `admin123456`

---

## Task Matrix & Status Board

| Task ID | Component | Task Description | Assigned Agent | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DOC-01** | Documentation | Complete Enterprise Project Documentation Suite | Antigravity AI | 🟢 DONE | 5 Full Spec Docs written in `/docs/` |
| **BE-01** | Backend | Configure WABA Django models (Channel, Session, Template, Log) | Session 1 (Backend) | 🟢 DONE (pre-existing) | Provided by `separator.waba` (37 migrations, all applied). Channel=`Phone`, Template=`Template`+component tree. Session model added under BE-03 (now 38 migrations). |
| **BE-02** | Backend | Implement Meta Webhook Receiver & HMAC verification | Session 1 (Backend) | 🟢 DONE (pre-existing) | `WabaWebhook` at `separator/waba/api/views.py:99`; `hub.verify_token` challenge at `:135`; HMAC SHA-256 verify at `separator/waba/utils.py:1446-1467`. |
| **BE-03** | Backend | Implement 24h Session Window Manager | Session 1 (Backend) | 🟢 DONE | `SessionWindow` model + migration `0038_sessionwindow` (applied). Anchored on inbound customer messages at `separator/waba/utils.py:1748`. 13 unit tests green. |
| **BE-04** | Backend | Implement Bitrix `imconnector` inbound/outbound handler | Session 1 (Backend) | 🟢 DONE (pre-existing) | `imconnector.register/activate/send.messages/send.status.delivery` in `separator/bitrix/utils.py` + `tasks.py`; inbound dispatch at `separator/waba/utils.py:1600-2170`. |
| **BE-05** | Backend | Expose REST endpoints for Frontend Session 2 (template list, template send, 24h window status) | Session 1 (Backend) | 🟢 DONE | Delivered on **two surfaces** — see BE-05 note below. Bitrix placement actions (`send`, `window_status`) for the in-portal widget, plus a general REST API under `/api/waba/` for out-of-portal clients. 6 + 23 unit tests green. |
| **BE-03e** | Backend | Enforce window on outbound free-form replies from Bitrix | Session 1 (Backend) | 🟢 DONE | Gate at `separator/bitrix/utils.py:1605-1620`. Templates exempt. Off by default behind `WABA_ENFORCE_SESSION_WINDOW`. |
| **FE-04** | Frontend | Repoint widget off the dead `/api/v1/*` sidecar paths | Session 2 (Frontend) | 🟢 DONE | Widget now calls `/api/waba/session-window/`, `/api/waba/templates/`, `/api/waba/templates/send/` with DRF auth. Verified against a mock of the BE-05 contract. |
| **FE-05** | Frontend | Sender phone discovery — no API exists | Session 2 (Frontend) | 🔴 **BLOCKED ON BACKEND** | Every agent endpoint requires `phone_id`, but nothing lists the phones a user may operate. Widget currently takes it from `?phone_id=` or ⚙ settings. Requesting `GET /api/waba/phones/` from Session 1. |
| **ARCH-01** | Architecture | Resolve duplicate stack: `separator.waba` (Django) vs `a7_waba_*.py` (FastAPI) | Lead Backend | 🟢 RESOLVED | **Decision: `separator.waba` is the system of record; transport goes direct to Meta Cloud API (not ALOTS.IO).** `a7_waba_*.py` is superseded — see Retirement below. |
| **ARCH-02** | Architecture | Retire superseded `a7_waba_*.py` sidecar modules | Lead Backend | ⏳ AWAITING OWNER SIGN-OFF | Files are dead code (nothing imports them; FastAPI not installed). Not deleted without explicit approval. |
| **FE-01** | Frontend | Build 24h Session Window UI Widget (`a7_waba_widget.html`) | Session 2 (Frontend) | 🟢 DONE | Live countdown (drift-corrected), colour states, session-aware mode banner |
| **FE-02** | Frontend | Implement Meta Approved Template Dropdown & Parameter Inputs | Session 2 (Frontend) | 🟢 DONE | Positional + named params across HEADER/BODY/BUTTONS; category grouping + filter |
| **FE-03** | Frontend | Implement Live Outbound Template Sender & Status Feedback | Session 2 (Frontend) | 🟢 DONE | Meta-error detection, wamid feedback, window state applied from send response |
| **QA-01** | Integration | Local Mock End-to-End Test Suite | Team (Session 1 + 2) | 🟡 IN PROGRESS | Frontend verified in-browser against a BE-05-shaped mock. **Not yet run against the real Django server** — needs a logged-in session, a seeded `Phone`, and templates. |

---

## Agent Communication & Handover Log

### [Session 1 - Backend Agent] Updates:
- WABA Django models migrated in local SQLite DB.
- Django dev server active on `http://127.0.0.1:8000/admin/`.
- Meta WABA API Cloud endpoints stubbed in `a7_waba_meta_client.py`.

### [Session 1 - Backend Agent] Updates — 2026-08-02 (Lead Backend Engineer):
- **ARCH-01 decided**: `separator.waba` is the system of record; WABA transport is **direct to Meta Cloud API**. The `a7_waba_*.py` FastAPI sidecar is superseded and must not be built against.
- **BE-03 complete**: `SessionWindow` model, migration `0038_sessionwindow` generated and applied to local SQLite. Window is anchored on inbound customer messages inside the existing webhook processor.
- **BE-05 complete**: audit found the template selector and outbound template sender **already shipped** as `WabaPlacementModule` actions — no duplicate built. Added the missing `window_status` action.
- **Tests**: `python manage.py test separator.waba` → **19 passed**. `python manage.py check` → clean.
- `SessionWindow` registered in Django admin (open/closed indicator + expiry) for local inspection at `/admin/`.
- **ARCH-02 open**: `a7_waba_config.py`, `a7_waba_session.py`, `a7_waba_meta_client.py`, `a7_waba_bitrix_client.py`, `a7_waba_connector.py` are now dead code. Left in place pending owner sign-off to delete.

### [Session 2 - Frontend Agent] Updates:
- Embedded WABA Side Panel Widget prototype created in `a7_waba_widget.html`.
- Template selector and dynamic parameter form built for `{{1}}`, `{{2}}` variables.

### [Session 2 - Frontend Agent] Updates — 2026-08-02 (Lead Frontend Engineer):

**FE-01/02/03 complete; FE-04 blocker cleared.** `a7_waba_widget.html` was rewritten and now targets the
BE-05 Django agent API. Verified in a real browser (Playwright) against a mock reproducing the BE-05
response shapes — session window, template list, send success, and Meta rejection.

**Correctness bugs found in the previous widget and fixed** (all would have shipped to agents):
1. **False success on failed sends.** The old code branched on HTTP 200 only, so a Meta rejection wrapped in
   a 200 body rendered as "✅ sent". Now inspects the Meta payload and surfaces code + `error_data.details`.
2. **Template variables sent in the wrong order.** Params were collected in DOM order, so a body reading
   `{{2}} … {{1}}` transmitted values swapped. Now sorted numerically before building `parameters[]`.
3. **Media headers always sent as `type:"image"`,** corrupting DOCUMENT and VIDEO templates. Now keyed off
   the component format, with `filename` for documents.
4. **`BACKEND_URL = window.location.origin`** — resolves to the customer's Bitrix portal inside a placement
   iframe, never the backend. Now explicit config with `?api=` / localStorage / `<meta>` precedence.
5. **HEADER-text and BUTTON-URL variables were ignored** (BODY only), and named `{{name}}` params were
   unsupported despite the data model having them. All three scopes now render inputs; named params emit
   `parameter_name`.
6. **`BX24.fitWindow` threw on every template change.** The Bitrix loader defines `BX24` as *null* when it
   cannot initialise, so `typeof BX24 !== 'undefined'` is not a sufficient guard. Now null-checked.

**Also added:** live drift-corrected countdown (anchored to `performance.now()`, not the agent's wall clock,
which may be skewed), colour states (>4 h / 1–4 h / <1 h / expired), session-aware mode banner, dark+light
theming with auto-detect, APPROVED-only filtering, category grouping and name filter for large template
sets, per-parameter validation against Meta's rules (no tabs / 4+ consecutive spaces), a WhatsApp-style
live preview, and `aria-live` status announcements.

**Semantics honoured:** the widget states that sending a template does **not** reopen the 24-hour window —
only an inbound customer reply does. It applies the `window` object returned by the send response rather
than re-polling.

**Requests to Session 1 (Backend):**
- **FE-05 / blocking:** no endpoint lists the phones a user may operate, but `phone_id` is mandatory on all
  three agent endpoints. Requesting `GET /api/waba/phones/` returning `[{phone_id, phone, label, waba_id}]`
  scoped by the same rules as `_resolve_agent_phone`. Until then the sender is configured by hand, which is
  not viable for 50 agents.
- **Non-blocking:** a lightweight `GET /api/waba/health/` would let the widget show a connection state
  before a phone is configured; it currently infers connectivity from the first real call.

**Note on my earlier session work:** before ARCH-01 was visible in this tree I added
`GET /api/v1/session/status` and `WABAStore.get_client_session()` to the now-superseded
`a7_waba_connector.py` / `a7_waba_session.py`. Those additions are **dead code under ARCH-01** and should be
removed along with the rest of the sidecar under ARCH-02. Nothing references them.

---

## Backend Audit — 2026-08-02 (Lead Backend Engineer)

Verified against the working tree, not against prior log claims. Corrections to the entries above are noted in the matrix.

### A. This workspace is an existing production platform, not a greenfield build
The repo is the **`separator`** Bitrix24 integration platform: 81 DB tables, `separator.waba` (37 migrations) and `separator.bitrix` (44 migrations), all applied. `python manage.py check` → *no issues*. Superuser `admin@example.com` exists. All WABA/Bitrix business tables are currently **empty (0 rows)** — schema is live, no data seeded.

Most of what the architecture doc lists as "to build" already ships:

| Architecture pillar | Actual state |
| :--- | :--- |
| Pillar A — Multi-number routing | **Already implemented.** `Phone.line` FK → `bitrix.Line` → `connector.code` + `line_id`. Drives every inbound dispatch. Not capped at 50; capacity is a data question, not a code one. |
| Pillar B — 24h session window | **Missing entirely.** The one genuine backend gap. |
| Pillar C — `imconnector` integration | **Already implemented**, incl. delivery-status callbacks, retry policy, and file proxying. |

### B. Two disconnected stacks now exist (ARCH-01)
The root `a7_waba_*.py` modules are a **second, parallel implementation** that is not wired into Django in any way:
- `a7_waba_connector.py` is a **FastAPI** app, not Django. `fastapi`/`uvicorn`/`pydantic` are **absent from every requirements file and not installed** — it cannot currently run.
- `a7_waba_session.py` writes to a **separate raw-sqlite3 DB** (`data/waba_connector.db`), duplicating session/message-log storage outside the Django ORM.
- No Django URLconf, setting, or module imports them. Only `a7_waba_widget.html` is referenced (from `/docs/` prose).
- `a7_waba_config.py` targets **ALOTS.IO** as the WABA transport, which contradicts the "no third-party SaaS" premise in `SYSTEM_ARCHITECTURE.md` §1.

Running both means two sources of truth for session windows and message logs. **Resolution required before further backend work.**

### C. Local runtime constraint for QA-01
Webhook processing is **asynchronous** — `WabaWebhook.create()` only calls `task.delay(...)`. Meaningful local end-to-end testing therefore needs **Redis + a Celery worker on the `waba` queue**; without them, mock webhooks return `200` and are silently dropped. Ambient interpreter is Python 3.14.6 / Django 6.0.7.

### D. Unrelated pending change in working tree
`config/settings/base.py` has an uncommitted `LANGUAGE_CODE` edit (`"ru"` → `"en-us"`). Not mine; left untouched.

### E. Concurrent agent activity in this workspace — 17:30–17:45
Another agent was editing this same tree during this session. It independently generated and applied
`0038_sessionwindow`, registered `SessionWindowAdmin`, wrote `separator/waba/tests.py`, and added the
`window_status` placement action — while this session was editing `models.py`, `utils.py` and `PROJECT_TASKS.md`.
No conflicts survived (full suite green), but **two agents on one working tree is not safe** and should be
serialised before the next change.

### F. Pre-existing bug fixed to unblock testing
`config/settings/test.py:36` set `MEDIA_URL = "http://media.testserver"` with no trailing slash, which modern
Django rejects (`urls.E006`). This made *every* test run abort before collection, so no test in this repo could
have been running. Fixed by appending the slash. Any earlier "tests green" claim predating this fix was not
actually executed against a working runner.

---

## BE-05 API Specification — Agent Widget

Two surfaces exist deliberately; pick by where the caller runs.

### Surface 1 — Bitrix placement actions (in-portal widget)
Authenticated by Bitrix (`auth_id` / `AppInstance`). Dispatched in `separator/bitrix/placements.py:853`.
Use this from inside a Bitrix placement iframe.

| Action | Handler | Purpose |
| :--- | :--- | :--- |
| `send` | `_send_template_action` | Send an approved template (pre-existing) |
| `send_interactive` | `_send_interactive_action` | Send an interactive message (pre-existing) |
| `window_status` | `_window_status_action` | 24h window state for (sender phone, customer) |

### Surface 2 — REST API (out-of-portal clients)
Django-authenticated (session, `Authorization: Token <token>`, or `?api-key=`). Access is scoped per phone:
owner, superuser, or Bitrix portal admin when `availabletoB24admins` is set. Registered in `config/urls.py`.

**`GET /api/waba/session-window/?phone_id=<>&customer_phone=<>`**
```json
{ "phone_id": "123", "customer_phone": "+79991234567", "open": true,
  "window_hours": 24, "enforced": false,
  "last_inbound_at": "2026-08-02T09:00:00+00:00",
  "expires_at": "2026-08-03T09:00:00+00:00", "remaining_seconds": 60840,
  "can_send_freeform": true, "can_send_template": true }
```

**`GET /api/waba/templates/?phone_id=<>[&status=APPROVED|all]`**
Returns `{phone_id, count, templates[]}`. Each template carries `components[]` and a flattened
`params: {named[], positional[]}` so the widget can render `{{1}}` / named inputs.

**`POST /api/waba/templates/send/`**
```json
{ "phone_id": "123", "customer_phone": "+79991234567", "template_id": "tmpl-1",
  "params": {"first_name": "Ali"}, "positional": ["12:00"] }
```
`components` may be supplied instead for a raw Meta-format passthrough, which overrides `params`/`positional`.
Parameter values containing `|` (or names containing `:`) are rejected with 400 rather than silently corrupted,
because the reused shortcode builder is `|`-separated — use `components` for those.

### Widget migration map (FE-04)
| Widget calls today (dead) | Use instead |
| :--- | :--- |
| `GET /api/v1/session/status?client_phone=` | `GET /api/waba/session-window/?phone_id=&customer_phone=` |
| `GET /api/v1/templates` | `GET /api/waba/templates/?phone_id=` |
| `POST /api/v1/templates/send` | `POST /api/waba/templates/send/` |
| `GET /api/v1/lines` | No equivalent — routing is `Phone.line` in Django admin, not a runtime API |
| `GET /api/v1/health` | No equivalent needed |

### Semantics worth preserving
Sending a template **does not** reopen the 24h window — only an inbound customer message does. The retired
`a7_waba_session.py` sidecar called `touch_client_session()` on template send, which was incorrect against
Meta's rules; that behaviour was deliberately not carried over.

---

## Backend API Spec for Session 2 (Frontend) — delivered 2026-08-02

**Important for FE-01/02/03:** do not build against the `a7_waba_connector.py` FastAPI routes (`/api/v1/...`). Per ARCH-01 they are superseded and that service does not run. All three capabilities are served by the existing Bitrix placement endpoint.

**Endpoint:** `POST /placement/` (Django, `separator/bitrix/urls.py` → `process_placement`)
**Auth:** Bitrix placement context — pass through `AUTH_ID` and `member_id` exactly as Bitrix posts them. No separate API key.
**Dispatch:** the `action` field selects the operation. Responses are JSON `{"ok": bool, ...}` with HTTP 200 even on logical failure — **branch on `ok`, not status code.**

### 1. Template selector (FE-02) — already existed
Templates are delivered in the widget render context, not fetched separately: `templates_data_by_phone` maps `sender_phone_id` → serialized approved templates (name, lang, components, variable placeholders). Only `status="APPROVED"` and `availableInB24=True` templates appear. Sender list is in `sender_phones`.

### 2. Outbound template sender (FE-03) — already existed
```
action=send
sender_phone_id=<Phone.id>
phone=<recipient msisdn>
template_id=<Template.id>
bitrix_user_id=<optional>
<component params + file uploads via multipart>
```
→ `{"ok": true, "result": {...Meta response...}}` or `{"ok": false, "error": "..."}`. Also writes a CRM timeline comment.

### 3. 24h window status (FE-01) — **new, added by this session**
```
action=window_status
sender_phone_id=<Phone.id>
phone=<customer msisdn, any format — normalized server-side>
```
→
```json
{
  "ok": true,
  "open": true,
  "window_hours": 24,
  "enforced": false,
  "remaining_seconds": 84212,
  "expires_at": "2026-08-03T09:15:22+00:00",
  "last_inbound_at": "2026-08-02T09:15:22+00:00"
}
```
Drive the countdown from `remaining_seconds`. A customer never heard from returns `open: false` with `expires_at`/`last_inbound_at` as `null`. When `open` is `false`, restrict the agent to the template sender.

### BE-03 semantics worth knowing
- The window is scoped **per (business phone, customer)** — the same customer on two A7 numbers has two independent windows.
- Only an **inbound customer message** reopens it. Sending a template does **not** reopen the window.
- `system` messages and outbound echoes deliberately do not extend it.
- Out-of-order webhook delivery never moves the anchor backwards.
- Duration is configurable via `WABA_SESSION_WINDOW_HOURS` (default 24).
- `WABA_ENFORCE_SESSION_WINDOW` (default `False`) is currently **advisory only** — the backend reports window state but does not yet block outbound free-form sends. Surfaced as `enforced` in the payload. See QA-01.

---

## Rules for AI Team Operations
1. **Local-First Rule**: Work ONLY inside `C:\Users\Matloob\Desktop\a7-full-whatsapp-system`. Do NOT modify AWS or live Bitrix until local verification is 100% complete.
2. **Task Log Updates**: Whenever a task is started, updated, or completed, update its status in `PROJECT_TASKS.md`.
3. **No Direct Production Mutations**: Test every API endpoint and UI widget locally first.
