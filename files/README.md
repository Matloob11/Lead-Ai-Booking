# Working files (not product code)

Loose spreadsheets, screenshots, briefs, and temp dumps live here so the
repo root stays the product. **Do not put app code in this folder.**

Next change mention karte waqt folder + screen bolo, jaise:
`inbox sidebar` · `campaigns Excel` · `Bitrix CRM access` · `Official numbers`

## This folder

| Folder | Kya rakho | Mention |
|--------|-----------|---------|
| `files/images/` | Screenshots (inbox, leads, OpenWA frame, branding) | "images / inbox sidebar" |
| `files/campaigns/` | Campaign Excel/CSV (A7 Jobs, CV interview) | "campaigns spreadsheet" |
| `files/briefs/` | PDFs (Official numbers list, monitoring brief, agents details) | "briefs / Official numbers PDF" |
| `files/crm/` | Team/community allocation, Dubai account sheet | "crm allocation sheet" |
| `files/temp/` | `.tmp_*`, Playwright dumps — gitignored | scratch only |

## Product folders (code — yahan change hota hai)

| Bolna | Folder | Live kahan |
|-------|--------|------------|
| Official inbox / panel | `bitrix/public/` | `https://wa.srv1802669.hstgr.cloud/app/` |
| Official API / webhooks / campaigns backend | `backend/apps/` | Hostinger Docker `web` + `worker` + `beat` |
| Numbers + templates | `backend/apps/catalog/` | Admin Numbers screen |
| Inbox chats/messages | `backend/apps/inbox/` + `bitrix/public/assets/modules/inbox.js` | Inbox |
| Campaigns send | `backend/apps/campaigns/` + `bitrix/public/assets/modules/campaigns.js` | Campaigns screen |
| Alots gateway | `backend/apps/gateway/` | Webhook `/api/gateway/webhook/alots/` |
| Agents / login | `backend/apps/accounts/` | SSO from Bitrix |
| Linked devices (unofficial) | `openwa/` + `wa-qr/` | OpenWA stack on same VPS |
| Agent daily reports | `agent-reports/` | `/agent-reports/` |
| Bitrix CRM patches (calls, TL mask, roles) | `ops/bitrix-aws/` + `handoff/bitrix-crm-access/` | `crm.a7grouprealestatedxb.com` |
| Deploy / nginx | `deploy/` + `ops/wa.sh` | `/opt/a7-wa/` |
| Old prototypes | `reference/` | not deployed |
| Specs | `docs/` | not deployed |

## Four live stacks

1. **Official WhatsApp API** — Meta via alots.io (WBBOX). `backend/` + `bitrix/public/`.
2. **Linked devices (OpenWA)** — phone QR sessions. `openwa/` + `wa-qr/`.
3. **Agent reports** — Bitrix deals/owners → PDF. `agent-reports/`.
4. **Bitrix CRM itself** — AWS portal. Patches in `ops/bitrix-aws/` and `handoff/`.
