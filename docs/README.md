# A7 Group — WhatsApp Lead-Control System · Documentation

Complete technical documentation set. Start with the concept doc, then read by area.

## Read order

| # | Doc | What it covers |
|---|-----|----------------|
| 00 | [System Concepts (Master)](00-system-concepts.md) | The whole system in plain terms + glossary + roadmap |
| 10 | [WhatsApp Cloud API](10-whatsapp-cloud-api.md) | Webhook, signature, send/receive, media, status, tiers |
| 11 | [Multi-Number Management](11-multi-number-management.md) | Number registry, routing, assignment, per-number health |
| 12 | [24h Window & Templates](12-window-and-templates.md) | Service window logic + template lifecycle |
| 13 | [Consent & Ban-Safety](13-consent-and-ban-safety.md) | Opt-in, warm-up, quality monitoring, outreach engine |
| 20 | [Backend Architecture](20-backend-architecture.md) | Modules, queues, REST API, realtime, RBAC |
| 30 | [Database Schema](30-database-schema.md) | Full PostgreSQL DDL + ER model + indexes |
| 40 | [Frontend Web App](40-frontend-web-app.md) | Agent workspace + manager dashboard, screens, realtime |
| 50 | [AI Intelligence (OpenAI)](50-ai-intelligence.md) | Sentiment/seriousness/intent scoring, prompts, alerts |
| 51 | [Duplicate-Client Detection](51-duplicate-detection.md) | Same customer, two agents → alert + reassign |
| 52 | [Competitor-Agent Detection](52-competitor-detection.md) | 30k–100k number DB, instant banner |
| 53 | [Cost Control](53-cost-control.md) | Meta pricing, save-money logic, reporting |
| 60 | [Bitrix24 Sync](60-bitrix24-sync.md) | Two-way CRM sync, custom fields, n8n glue |
| 70 | [Security & Compliance](70-security-and-compliance.md) | Secrets, auth, PDPL/TDRA, retention, audit |
| 80 | [Deployment & Infra](80-deployment-and-infra.md) | Hosting (AWS/Hostinger), go-live, backups, monitoring |

## wacrm adaptation (chosen base — do not build from scratch)

We fork the open-source **wacrm** (Next.js + Supabase + official Cloud API, MIT) instead of greenfield.

| # | Doc | What it covers |
|---|-----|----------------|
| 90 | [wacrm Gap Analysis](90-wacrm-gap-analysis.md) | wacrm features ↔ Docs 10–80, per-gap modification plan, build order |
| 91 | [Multi-Number Modification](91-multi-number-modification.md) | Exact schema diff (migration 037) + files to change for many numbers/account |
| 92 | [Local Setup Guide](92-local-setup-guide.md) | Run wacrm locally (Windows): install → Supabase → migrations → Meta → dev |

> **Stack note:** wacrm uses Next.js API routes + Supabase (Auth/RLS/Realtime/Storage), not the
> Express+Socket.IO+BullMQ stack in Docs 20/30/80. Concepts hold; those three docs get revised
> for the Supabase stack. wacrm base is at [`../wacrm-main/`](../wacrm-main/).

## Confirmed project decisions

- WhatsApp = **Official Meta Cloud API** (keys/Business-ID via the webbox/allots.io panel).
- Frontend = **Web app** (browser, real-time, media). No mobile app.
- **Multiple** WhatsApp numbers (per team/community/agent).
- Outreach = **cold + incoming** (with opt-in + ban-safety controls).
- **Bitrix24** two-way sync + **OpenAI** scoring — both in scope.
- Media storage abstracted (local disk → S3/R2 swappable).

## Source

Original brief: [`../source/A7_WhatsApp_System_Spec.pdf`](../source/A7_WhatsApp_System_Spec.pdf)
(reviewed; fixes for its gaps — signature verification, message status, multi-number, consent,
audit log, updated pricing — are baked into these docs).

## Build order

Core first (10 · 11 · 12 · 13 · 20 · 30 · 40) → intelligence (50 · 51 · 52 · 53) →
CRM (60) → security/deploy (70 · 80). Ship the daily-use pieces before layering intelligence.
