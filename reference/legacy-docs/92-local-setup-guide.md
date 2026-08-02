# Doc 92 — Local Setup Guide (Run wacrm on your machine)

> Get the **unmodified** wacrm base running locally first, so you have a known-good baseline
> before applying A7 changes ([Doc 91](91-multi-number-modification.md), Gaps in [Doc 90](90-wacrm-gap-analysis.md)).
> Written for **Windows 10 + PowerShell** (this machine). Stack: Next.js 16 + Supabase.

---

## 0. What you need before starting

| Requirement | Notes |
|-------------|-------|
| **Node.js ≥ 20** | This machine has v24 — ✅ (`node -v` to confirm). |
| **Supabase** (SELF-HOSTED) | A7 runs its OWN Supabase (data stays on our server). For local dev use the Supabase CLI's local Docker stack (`supabase start`); for the server use the self-hosted Docker stack (§2). **Requires Docker.** |
| **Meta WhatsApp** (for live messaging) | WABA + a phone number + permanent token + App Secret. Can be added *after* the app runs. |
| **A public HTTPS tunnel** (for the webhook, local only) | e.g. `ngrok`, `cloudflared`. Meta must reach your webhook over HTTPS. |

> You can run the **UI** with just Supabase. WhatsApp send/receive needs the Meta creds + tunnel.
> Do the app-first, WhatsApp-second.

---

## 1. Install dependencies

The code is already in `wacrm-main/`. In PowerShell:

```powershell
cd "c:\Users\PC\Desktop\a7-full-whatsapp-system\wacrm-main"
npm install
```

> ⚠️ Before writing any code, note `AGENTS.md`: this is **Next.js 16** (newer than most
> training data). For setup you don't need to worry about it; for later edits, check
> `node_modules/next/dist/docs/`.

---

## 2. Supabase — SELF-HOSTED (A7 keeps its own data)

A7 does **not** use Supabase Cloud. We run Supabase (open-source) ourselves, so all data stays
on our machine/server. Supabase is Postgres **+ Auth + RLS + Realtime + Storage** — wacrm needs
all of it, and self-hosting changes **zero** app code (only the URL/keys point to our instance).

### 2a. Local development — Supabase CLI (Docker)
The fastest local path. Requires **Docker Desktop** running.

```powershell
npm i -g supabase          # Supabase CLI
cd "c:\Users\PC\Desktop\a7-full-whatsapp-system\wacrm-main"
supabase init              # once — creates supabase/config.toml
supabase start             # boots local Postgres+Auth+Storage+Realtime+Studio in Docker
```
`supabase start` prints your local **API URL**, **anon key**, and **service_role key** — copy
those into `.env.local` (§4). Local Studio opens at the printed URL (usually `http://localhost:54323`).

> The migrations in `supabase/migrations/` are applied automatically by `supabase start` /
> `supabase db reset`. No manual SQL pasting needed on this path.

### 2b. Server — self-hosted Supabase (Docker Compose on a VPS)
For staging/production on our own **Hostinger VPS** (or any VPS with Docker):
- Use Supabase's official self-host stack: `github.com/supabase/supabase` → `docker/`
  (`docker compose up -d`), set strong `POSTGRES_PASSWORD` / `JWT_SECRET` / keys in its `.env`.
- Then wacrm's `.env` points `NEXT_PUBLIC_SUPABASE_URL` at the VPS's Supabase API, with that
  instance's anon + service keys.
- Needs a VPS (Docker) — **not** Hostinger's shared "Managed Node.js" plan. See [Doc 80](80-deployment-and-infra.md).

---

## 3. Run the database migrations (in order)

The repo ships 36 SQL migrations in `supabase/migrations/` (`001_…` → `036_…`). There's **no
CLI config bundled**, so the simplest path is the Supabase SQL editor:

**Option A — SQL editor (easiest):**
1. Supabase dashboard → **SQL Editor**.
2. Open each file `001_initial_schema.sql` … `036_conversation_contact_dedup.sql` **in numeric
   order**, paste, and **Run**. They are idempotent (safe to re-run).
   - Migration `030_ai_knowledge.sql` runs `CREATE EXTENSION vector` — Supabase has pgvector
     available, so it just works.

**Option B — Supabase CLI (if you prefer):**
```powershell
npm i -g supabase
supabase login
supabase link --project-ref <your-project-ref>
# place the migrations under supabase/migrations (they already are) then:
supabase db push
```

> Order matters — later migrations alter earlier tables. Don't skip any.

---

## 4. Configure `.env.local`

Copy the example and fill it in:

```powershell
Copy-Item .env.local.example .env.local
```

Generate the token-encryption key (32 bytes hex) — required:

```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

Minimum required keys in `.env.local`:

```ini
NEXT_PUBLIC_SUPABASE_URL=https://<your-project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>
ENCRYPTION_KEY=<64-hex-char output from the command above>
META_APP_SECRET=<from Meta App → Settings → Basic>   # needed for the webhook to accept posts
```

Recommended while developing (skips real Meta calls when submitting templates):

```ini
WHATSAPP_TEMPLATES_DRY_RUN=true
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

> `META_APP_SECRET` is required for the **webhook POST** to pass signature verification. If
> you're only clicking around the UI (no inbound messages yet), any placeholder lets the app
> boot; set the real value before testing inbound.

---

## 5. Run the app

```powershell
npm run dev
```

Open <http://localhost:3000> → you'll be redirected to `/login`.

1. **Sign up** (creates your account — you become the `owner`).
2. You land on `/dashboard`. The UI now works end-to-end against Supabase.

Sanity checks:
```powershell
npm run typecheck   # should pass
npm run test        # vitest suite — should pass
```

---

## 6. Connect WhatsApp (to send/receive for real)

### 6.1 In the app
Go to **Settings → WhatsApp** and enter:
- **Phone Number ID** (Meta)
- **Permanent access token** (System User token)
- **Verify token** (any secret string you choose — you'll paste the same one into Meta)

The app stores the token AES-256-GCM-encrypted (`ENCRYPTION_KEY`).

### 6.2 Expose the webhook publicly (local dev)
Meta needs a public HTTPS URL. Start a tunnel to port 3000:

```powershell
# example with ngrok
ngrok http 3000
```
Your webhook URL becomes: `https://<random>.ngrok-free.app/api/whatsapp/webhook`

### 6.3 Register the webhook in Meta
In Meta (App → WhatsApp → Configuration):
- **Callback URL:** `https://<tunnel>/api/whatsapp/webhook`
- **Verify token:** the same string you entered in Settings → WhatsApp.
- Subscribe to the **`messages`** field.
- Meta sends a GET to verify → the app echoes the challenge → ✅ verified.

### 6.4 Test
- Send a WhatsApp message **to** your business number → it should appear in the **Inbox** live.
- Reply from the inbox → the customer receives it from the company number.
- Send a template / broadcast (with `WHATSAPP_TEMPLATES_DRY_RUN=true` you can build templates
  without a live WABA; turn it off for real sends).

---

## 7. (Optional) AI, MCP

- **AI reply assistant:** Settings → AI Assistant → paste your **OpenAI** key (stored encrypted).
  Then you get draft replies / auto-reply / knowledge base. *(A7's lead-scoring feature — Gap 4
  in [Doc 90](90-wacrm-gap-analysis.md) — will reuse this same key/provider.)*
- **MCP server:** create an API key (Settings → API keys) and point Claude/Cursor at
  `wacrm-mcp` — see `wacrm-main/docs/mcp.md`.

---

## 8. Common issues

| Symptom | Fix |
|---------|-----|
| App boots but login errors | Supabase URL/anon key wrong, or migrations not run (no `profiles` table). |
| Webhook GET fails in Meta | Verify token mismatch between Settings → WhatsApp and Meta. |
| Webhook POST 401 | `META_APP_SECRET` missing/wrong (signature check fails). |
| Inbound message not showing | Not subscribed to `messages`, or tunnel down, or `SUPABASE_SERVICE_ROLE_KEY` missing (webhook uses admin client). |
| Images show as empty bubbles | Media proxy needs the access token; confirm the number's token is saved + valid. |
| `vector` extension error on migration 030 | Enable the `pgvector` extension in Supabase (Database → Extensions) then re-run. |

---

## 9. After the baseline works — the A7 path

Once inbound → inbox → reply works on **one** number:

1. **Fork/version-control it.** Put `wacrm-main` under git (it's greenfield here) so A7 changes
   are tracked and upstream is recoverable.
2. Apply **[Doc 91 — Multi-number](91-multi-number-modification.md)** (migration 037 + the code edits).
3. Add A7 features in the order from **[Doc 90 §5](90-wacrm-gap-analysis.md)** (window gating →
   competitor/duplicate → lead scoring → consent → cost/audit → Bitrix via n8n).
4. Rebrand (navy & gold, A7 logo) and pilot with 3–5 agents.

> **Deploy target:** the same app runs on **Hostinger Managed Node.js** (wacrm's recommended
> path) or any Node host, with Supabase as the managed DB — matches [Doc 80](80-deployment-and-infra.md).

---

*Back to: [Doc 90 gap analysis](90-wacrm-gap-analysis.md) · [Doc 91 multi-number](91-multi-number-modification.md) · [docs index](README.md).*
