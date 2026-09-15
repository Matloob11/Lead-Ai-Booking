# OpenWA Legacy Identity Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-write, sanitized OpenWA legacy identity audit that classifies every stored session as PASS, FAIL, or INCONCLUSIVE and exposes exit codes 0, 2, and 1 respectively.

**Architecture:** A self-contained TypeScript module owns strict account-identity normalization, persisted-LID resolution, per-session classification, sanitized formatting, and the read-only SQLite entrypoint. `ops/openwa/identity-audit.sh` transpiles that exact source locally, sends it base64-encoded over SSH stdin, and executes it as a one-off Node process in the running OpenWA container; `DatabaseSync` opens the fixed database path with `readOnly: true` and the application does not boot.

**Tech Stack:** TypeScript, Jest, Node.js `node:sqlite`, Bash, Docker, SSH, SQLite.

## Global Constraints

- Read only: no UPDATE, migration, app/session restart, source deploy, credential change, or persistent remote file.
- Inspect only `sessions.phone`, message `direction` plus inbound `to`/outbound `from`, and persisted `lid_mappings`.
- Normalize exact phone identities across `@c.us` and `@s.whatsapp.net`; never infer phone digits from an unresolved `@lid`.
- Output only safe session labels, row/resolved/unresolved counts, per-session decision, and overall decision.
- Never print phone/JID values, message content or names, API keys, tokens, credentials, DB paths, raw errors, or unsafe session labels.
- Exit 0 for overall PASS, 1 for INCONCLUSIVE/tool failure, and 2 for FAIL.
- Do not modify Django, Bitrix, wa-qr, OpenWA runtime enforcement, schema, migrations, or live service state.

---

### Task 1: Tests-first identity classifier

**Files:**

- Create: `openwa/src/modules/session/legacy-identity-audit.spec.ts`
- Create later: `openwa/src/modules/session/legacy-identity-audit.ts`

**Interfaces:**

- Consumes: session `{ id, name, phone }`, message `{ sessionId, direction, from, to }`, and LID mapping `{ lid, phone }` rows.
- Produces: `auditSessions(input): AuditReport`, `formatAuditReport(report): string`, and `exitCodeForDecision(decision): 0 | 1 | 2`.

- [ ] Write literal fixtures proving `@c.us` and `@s.whatsapp.net` collapse to one phone identity.
- [ ] Write literal fixtures proving mapped `@lid` resolves while missing/null/unparseable mapping increments unresolved without guessing.
- [ ] Write a two-owner fixture that must FAIL even when bound phone is absent.
- [ ] Write a null-bound session with stored rows that must be INCONCLUSIVE.
- [ ] Write a clean bound session that must PASS.
- [ ] Write sanitization and overall-precedence tests: raw phones/LIDs/body/token/path/unsafe label never occur; FAIL outranks INCONCLUSIVE, which outranks PASS; exit codes are exact.
- [ ] Run `cd openwa && npx jest src/modules/session/legacy-identity-audit.spec.ts --runInBand`; expect module-not-found failure.

### Task 2: Minimal pure implementation and read-only adapter

**Files:**

- Create: `openwa/src/modules/session/legacy-identity-audit.ts`
- Test: `openwa/src/modules/session/legacy-identity-audit.spec.ts`

**Interfaces:**

- `normalizeAccountIdentity(value, lidMappings)` accepts only strict phone values, `@c.us`, `@s.whatsapp.net`, or exactly persisted `@lid` mappings.
- `auditSessions({ sessions, messages, lidMappings })` counts every stored message once using inbound `to` or outbound `from`.
- `auditDatabase(path)` opens SQLite with `{ readOnly: true }`, selects only required identity columns, and never initializes Nest or TypeORM.
- `runCli(path)` prints only formatted report; any adapter/tool error prints `overall: INCONCLUSIVE` and returns 1 without raw error text.

- [ ] Implement strict normalization: optional phone formatting is accepted only when the whole value is a 7-15 digit E.164-shaped phone; JID local part follows the same rule; device suffix is removed; LID user part is used only as exact mapping key.
- [ ] Implement decision order: distinct resolved owners or bound-owner mismatch is FAIL; otherwise missing/unparseable bound phone or any unresolved row is INCONCLUSIVE; otherwise PASS.
- [ ] Implement overall decision order and safe label fallback `session-<ordinal>` for names outside `[A-Za-z0-9._-]{1,100}`.
- [ ] Implement read-only SQLite queries for `sessions`, `messages`, and optional `lid_mappings`; select no body, chat name, metadata, key, or credential field.
- [ ] Run focused Jest test; expect all audit tests pass.

### Task 3: Sanitized remote runner

**Files:**

- Create: `ops/openwa/identity-audit.sh`

**Interfaces:**

- Reads: local `openwa/src/modules/session/legacy-identity-audit.ts` and local `openwa/node_modules/typescript`.
- Runs: fixed Hostinger host/key/image/volume constants matching `ops/openwa/import-history.sh`.
- Emits: remote helper stdout only when remote exit is 0, 1, or 2; otherwise only `overall: INCONCLUSIVE`.

- [ ] Transpile exact TypeScript source to CommonJS in memory; base64-encode without writing a generated repo file.
- [ ] Pipe encoded source through pinned Windows OpenSSH stdin to `base64 -d | docker compose exec -T openwa-api node -`; invoke Node against fixed `/app/data/openwa.sqlite` without booting Nest, TypeORM, or any WhatsApp engine.
- [ ] Suppress SSH/Docker/raw compiler diagnostics; map any unexpected local or remote failure to sanitized INCONCLUSIVE exit 1.
- [ ] Run `bash -n ops/openwa/identity-audit.sh`; expect exit 0.

### Task 4: Regression, build, and live zero-write verification

**Files:**

- Modify: `TASKS.md` after evidence is complete.

- [ ] Run `cd openwa && npx jest src/modules/session/legacy-identity-audit.spec.ts --runInBand`.
- [ ] Run `cd openwa && npx jest src/modules/session src/engine --runInBand`; require no new failures and record exact suites/tests/skips.
- [ ] Run `cd openwa && npm run build`; require exit 0.
- [ ] Run `bash ops/openwa/identity-audit.sh`; record only sanitized lines and exact exit code.
- [ ] Confirm audit output does not contain known phone/JID values, `@`, message text, DB/source paths, API/token/key/credential terms, or unsafe raw errors.
- [ ] If any session is INCONCLUSIVE, run aggregate read-only SQLite queries that return session label and reason counts only; distinguish unmapped account-side LID from legacy missing/unparseable owner field.
- [ ] Run `git diff --check` and inspect scoped diff. Preserve unrelated dirty files.
- [ ] Add newest-first `TASKS.md` entry listing files, live results, cause analysis, verified commands, and explicit non-actions: no deploy/write/restart/migration/enforcement.
