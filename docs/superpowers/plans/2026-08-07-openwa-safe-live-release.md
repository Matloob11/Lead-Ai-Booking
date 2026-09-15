# OpenWA Safe Hostinger Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Audit, cold-back up, publish, migrate, and verify approved OpenWA history changes on Hostinger without changing Bitrix iframe ownership, disconnecting live WhatsApp, or allowing an old image to boot against migrated data.

**Architecture:** Extend constrained `ops/wa.sh` vocabulary with fixed release commands. Run a streamed, read-only identity pre-audit before any server write. Atomically stage committed OpenWA source, build a provenance-labeled candidate while old container remains live, audit candidate with data volume read-only, then stop API and archive entire named volume. Candidate boot is the migration boundary. After that boundary recovery is roll-forward unless user separately approves whole-volume destructive restore plus exact old image.

**Tech Stack:** Bash, Docker Compose, Docker, SQLite, Node.js, Hostinger VPS, Nest health endpoint, Playwright.

## Global Constraints

- Execute only after core and DB-first plans pass full local tests, review, and production builds.
- User approved deployment and additive migration. New destructive restore, data deletion, live unlink/relink, or old-image rollback still needs separate explicit approval.
- Deploy only OpenWA source/image. Never run `ops/wa.sh panel`, Django migration, Bitrix publish, n8n mutation, nginx change, or port/iframe-handshake change.
- Keep SSH operations inside fixed `ops/wa.sh` commands; expose no arbitrary remote shell, path, tag, service, or SQL argument.
- Streamed pre-audit must return PASS before server filesystem/source/build/service/data mutation. FAIL, INCONCLUSIVE, or tool error stops immediately.
- Never print phone numbers, message bodies, API keys, credentials, environment values, credential filenames, or archive member details.
- Never start old image with post-migration volume. Never run migration down/revert. Post-boundary failure is roll-forward.
- Do not disconnect, logout, re-pair, scan QR, send, react, delete, or force-reconnect production WhatsApp during verification.

---

## Task 1: Add sanitized legacy identity audit and cold-volume tools

**Files:**

- Create: `openwa/scripts/audit-session-identities.mjs`
- Create: `openwa/scripts/audit-session-identities.spec.mjs`
- Reuse: `openwa/test/fixtures/legacy-identity-audit.json`
- Create: `openwa/scripts/a7-cold-volume-backup.sh`
- Create: `openwa/scripts/a7-cold-volume-restore.sh`
- Create: `openwa/scripts/smoke-test-a7-cold-volume.sh`
- Modify: `openwa/package.json`
- Modify: `openwa/Dockerfile`
- Modify: `openwa/docker-compose.yml`
- Modify: `openwa/src/modules/docker/compose-parity.spec.ts`

- [ ] Reuse core golden audit fixtures for PASS, conflicting direct owner identity, missing/unparseable owner side, unresolved account-side LID, null bound identity with history, empty never-linked session, and mixed evidence. Assert standalone predeploy classifier matches runtime classifier's expected class/counts for every vector.
- [ ] Assert audit output contains counts and `PASS|FAIL|INCONCLUSIVE` only; fixture phone/JID/message values and database paths must not appear on stdout/stderr.
- [ ] Run `cd openwa && node --test scripts/audit-session-identities.spec.mjs`; expect failure because audit script does not exist.
- [ ] Implement read-only SQLite audit using `better-sqlite3` with `readonly: true, fileMustExist: true`. Read bound phone/checkpoint/status and direct-message owner side (`incoming.to`, `outgoing.from`), normalize only `@c.us`/`@s.whatsapp.net`, resolve LID only from persisted mapping, and never boot Nest/TypeORM migrations. Accept current-generation READY log evidence on stdin, parse it in memory, and classify missing/ambiguous evidence INCONCLUSIVE; never echo parsed values.
- [ ] Classification and exit contract:

```text
PASS         every provable account-side identity matches bound/current identity; none unresolved; exit 0
FAIL         at least one provable account-side identity conflicts; nonzero distinct exit
INCONCLUSIVE bound/current identity, owner side, or required persisted LID mapping is unproven; nonzero distinct exit
```

- [ ] Add cold-backup tests for whole mounted tree, numeric ownership metadata, mode `0600`/umask `077`, SHA-256 sidecar, `gzip -t`, tar traversal rejection, required `main.sqlite`/`openwa.sqlite`, extracted SQLite `PRAGMA quick_check`, and aggregate session/credential presence without filenames.
- [ ] Add cold-restore tests for exact whole-tree replacement into a dedicated empty target, checksum/path/DB validation before target mutation, and required literal `I_ACCEPT_POSTDEPLOY_DATA_LOSS`. Restore script must refuse root, home, workspace, source volume, symlink escapes, and non-empty targets unless a separately named forensic snapshot succeeds.
- [ ] Run `bash openwa/scripts/smoke-test-a7-cold-volume.sh`; expect failure before scripts exist.
- [ ] Implement backup from a read-only `/source` mount to a separate `/backup` mount. Archive every entry under source; do not substitute existing selective `backup.sh` for release snapshot. Keep `backup.sh`/`restore.sh` unchanged for routine logical backups.
- [ ] Add package script `test:identity-audit`. Copy audit, cold backup/restore, and `lib-env.sh` into production image. Add OCI labels/args for source digest, release ID, and build UTC.
- [ ] Set compose image deterministically:

```yaml
openwa-api:
  image: ${OPENWA_IMAGE_REF:-a7-openwa:local}
```

- [ ] Extend compose parity test to require named `openwa_openwa-data`, deterministic image ref, existing 45-second stop grace, and unchanged loopback/public port behavior.
- [ ] Rerun audit/cold-backup/Docker/compose tests; expect pass.
- [ ] Stage only Task 1 files and commit `feat(ops): add OpenWA identity and cold-backup gates`.

## Task 2: Add fixed Hostinger release commands

**Files:**

- Modify: `ops/wa.sh`
- Create: `ops/wa.spec.sh`
- Create: `docs/runbooks/openwa-lossless-history-release.md`

- [ ] Create fake `ssh.exe`, `scp.exe`, `tar`, `git`, and Docker-output contract tests. Assert every new argument is allowlisted, release ID is strict UTC format, paths remain under `/opt/openwa-trial`, and no command accepts arbitrary shell/path/tag/service/query text.
- [ ] Add negative tests for concurrent release marker, unhealthy current app, wrong volume, insufficient disk, identity non-PASS, stale audit receipt, source digest mismatch, missing/different image ID, missing backup/checksum, unhealthy candidate, and old-image selection after migration marker.
- [ ] Add regression test proving remote Docker command failure remains nonzero even when output is shortened. Remove `| tail` or enable remote `set -o pipefail` and explicitly preserve the Docker exit code for existing and new build/up commands.
- [ ] Run `bash ops/wa.spec.sh`; expect failure because commands do not exist.
- [ ] Add only these fixed commands:

```text
openwa-preaudit
openwa-begin
openwa-sync <release-id>
openwa-build <release-id>
openwa-audit <release-id>
openwa-backup <release-id>
openwa-resume-old <release-id>
openwa-deploy <release-id>
openwa-verify <release-id>
openwa-restore <release-id> I_ACCEPT_POSTDEPLOY_DATA_LOSS
```

- [ ] `openwa-preaudit`: stream current container logs since its start into a fixed in-container invocation of the local self-contained audit source (source is encoded in the command, never written remotely). Audit opens DB read-only and compares latest per-session READY identity evidence with bound/message evidence in memory. Missing/duplicate/unparseable current evidence is INCONCLUSIVE. Command echoes class/counts only, writes nothing remotely, and exits 0 only on PASS.
- [ ] `openwa-begin`: after PASS, generate/print one strict UTC release ID; create `/opt/openwa-trial/deploy-state/<release>` mode 700; record old running image ID, exact immutable tag `a7-openwa:pre-<release>`, compose/health, volume identity/size/free disk, and sanitized source/compose checksums. Refuse concurrent release or insufficient space.
- [ ] `openwa-sync <release>`: archive committed `openwa/` tree from recorded release revision, not dirty files; upload into fresh server staging; validate deterministic digest; preserve server `.env` mode 600; atomically swap staged source into `/opt/openwa-trial/OpenWA`. Never touch named volume, backups, nginx, Bitrix, or panel. Do not reuse generic `sync`, which nests basename and retains stale files.
- [ ] `openwa-build <release>`: set `OPENWA_IMAGE_REF=a7-openwa:candidate-<release>`, build API, record exact image ID/OCI labels, require source label/digest match and candidate ID differ from old. Old container remains live.
- [ ] `openwa-audit <release>`: pipe current old-container READY evidence into candidate entrypoint override with `openwa_openwa-data:/app/data:ro`, no app startup/network/migration, and require same PASS classification as pre-audit. Store only check class/counts/checksum receipt.
- [ ] `openwa-backup <release>`: recheck immutable PASS/build/source receipts; stop `openwa-api` with 45-second grace; assert stopped; run candidate cold-backup helper with volume mounted read-only and `/opt/openwa-trial/backups/<release>` mounted RW; verify SHA-256, gzip, path safety, required DBs, quick checks, and aggregate credential/session presence. Leave API stopped on success.
- [ ] `openwa-resume-old <release>`: allowed only when candidate migration-started marker is absent and volume fingerprint equals pre-stop fingerprint. Start exact tagged old image and verify image ID/health. This is a pre-migration abort path, not rollback.
- [ ] `openwa-deploy <release>`: require PASS candidate audit, verified cold backup, exact candidate image, stopped old API, and unchanged source receipts. Write migration-started marker, then run:

```bash
OPENWA_IMAGE_REF="a7-openwa:candidate-<release>" \
  docker compose up -d --no-deps --force-recreate openwa-api
```

- [ ] Once migration-started marker exists, every trap/error path must refuse `openwa-resume-old`, old tag, migration revert, or automatic restore.
- [ ] `openwa-verify <release>`: require running image ID equals candidate, OCI/source digest matches, container/local readiness healthy, public unauthenticated gate remains 401, expected migration/schema/index exists, `PRAGMA quick_check` is `ok`, duplicate count zero, and sanitized session/import state is acceptable. Store checksummed receipt.
- [ ] `openwa-restore`: always refuse unless literal confirmation present and external user approval was recorded by operator. Stop candidate, make verified postdeploy forensic full-volume archive, validate predeploy archive, restore whole dedicated volume, verify DB/counts, then start exact `a7-openwa:pre-<release>`. State that all postdeploy data is discarded.
- [ ] Add runbook exact commands, expected classifications, artifact/receipt paths, safe abort boundary, migration boundary, roll-forward steps, and destructive restore warning.
- [ ] Rerun `bash ops/wa.spec.sh`; expect pass.
- [ ] Stage only Task 2 files and commit `feat(ops): add guarded OpenWA release workflow`.

## Task 3: Complete local release gates and independent review

**Files:**

- Modify only for proven regressions: implementation files from all plans.

- [ ] Run backend/release gates from `openwa/`:

```powershell
npm ci
npm test -- --runInBand
npm run test:e2e -- --runInBand
npm run test:scripts
npm run test:identity-audit
npm run test:pg-smoke
npm run lint
npm run format:check
npm run build:all
npm run check:dockerignore
npm run openapi:check
docker compose config
```

- [ ] Run dashboard gates:

```powershell
cd openwa/dashboard
npm ci
npm run test:unit
npm run typecheck
npm run lint
npm run i18n:check
npm run build
```

- [ ] Run Bash gates:

```bash
bash -n ops/wa.sh openwa/scripts/a7-cold-volume-backup.sh openwa/scripts/a7-cold-volume-restore.sh
cd openwa
bash scripts/smoke-test-backup-restore.sh
bash scripts/smoke-test-a7-cold-volume.sh
cd ..
bash ops/wa.spec.sh
```

- [ ] Run `shellcheck` on changed shell files when installed; any skipped tool is reported, not silently treated as pass.
- [ ] Build production image locally with provenance args. Run it against temporary local SQLite volume; require additive migration and `/api/health/ready` 200.
- [ ] Run independent review against approved spec. Resolve correctness issues involving identity phase/order, awaited persistence, CAS, timeout teardown, deletion drain, DB-first reads, cursor boundaries, cold backup, and release boundary.
- [ ] Secret-scan diff and generated logs; remove identity/content/key/path leakage.
- [ ] Confirm `git diff --check` clean. Confirm release commit contains planned OpenWA/ops/docs only and excludes unrelated Django/Bitrix/ChatSidebar/a7-embedded WIP.
- [ ] Record full 40-character release commit and deterministic OpenWA source digest.

## Task 4: Run zero-write production preflight

**Files:** None.

- [ ] Run `bash ops/wa.sh ps`; require current OpenWA healthy.
- [ ] Run existing read-only `ops/wa.sh sql openwa` duplicate query; require zero duplicate `(sessionId, waMessageId)` groups.
- [ ] Run read-only session-state query returning counts by status and null/non-null identity/checkpoint buckets only.
- [ ] Run `bash ops/wa.sh openwa-preaudit`; require PASS. On FAIL/INCONCLUSIVE/tool error, stop before `openwa-begin` and report class/counts only.
- [ ] Compare current read-only image/source/compose checksums with known baseline. Explain drift before any upload.

## Task 5: Stage and build candidate while old app stays live

**Files:** None.

- [ ] Run `bash ops/wa.sh openwa-begin`; record returned release ID and old image ID/tag.
- [ ] Run `bash ops/wa.sh openwa-sync <release-id>`; require remote digest equals local release digest.
- [ ] Run `bash ops/wa.sh openwa-build <release-id>`; record candidate image ID and OCI labels. Confirm running container still uses old image and remains healthy.
- [ ] Run `bash ops/wa.sh openwa-audit <release-id>`; require PASS. On non-PASS, leave old container live and stop.

## Task 6: Cold-back up and cross migration boundary

**Files:** None.

- [ ] Reconfirm maintenance window, PASS receipt, disk space, candidate ID, source digest, and no concurrent release.
- [ ] Run `bash ops/wa.sh openwa-backup <release-id>`. Capture archive basename, SHA-256, byte size, required-entry aggregate, DB quick-check result, and stopped old image ID; never archive contents/credential names.
- [ ] If cold backup fails, use `openwa-resume-old` only after command proves no migration marker and unchanged volume fingerprint.
- [ ] Run `bash ops/wa.sh openwa-deploy <release-id>`. This is first candidate boot and additive migration boundary. Do not interrupt fixed remote operation.
- [ ] If candidate fails after migration marker, never resume old/restore/revert. Inspect sanitized candidate logs, fix forward locally, rerun gates, sync/build new candidate, and recreate candidate.

## Task 7: Verify live result without reconnecting WhatsApp

**Files:** None.

- [ ] Run `bash ops/wa.sh openwa-verify <release-id>` and `bash ops/wa.sh ps`; require candidate image/provenance, health, migration/schema/index, DB quick check, and duplicate check.
- [ ] Exact SQLite queries through constrained read-only command:

```sql
SELECT COUNT(*) FROM migrations WHERE name = 'AddLosslessHistorySyncState1786300000000';
SELECT COUNT(*) FROM pragma_table_info('sessions')
 WHERE name IN ('historyFirstLinkedAt','historySyncToken','historySyncError');
SELECT COUNT(*) FROM pragma_index_info('IDX_messages_sessionId_chatId_createdAt')
 WHERE name IN ('sessionId','chatId','createdAt');
SELECT COUNT(*) FROM (
  SELECT "sessionId", "waMessageId" FROM messages
  WHERE "waMessageId" IS NOT NULL
  GROUP BY "sessionId", "waMessageId" HAVING COUNT(*) > 1
);
PRAGMA quick_check;
```

- [ ] Expected results: migration `1`, columns `3`, index columns `3`, duplicate groups `0`, quick check `ok`.
- [ ] Inspect sanitized logs for migration success, accepted identity, one history run per session, awaited completion/failure class, progress below 100 on failure, and absence of phone/message/credential output.
- [ ] Call health and authenticated stored chat/message endpoints. Confirm cursor response contains `nextCursor` and `hasMore`; do not call live mutations.
- [ ] Use Playwright on direct OpenWA dashboard and existing Bitrix Linked Devices iframe. Confirm same iframe host/autologin, stored chat list/thread, older cursor page, chat switch during fetch, and no new console errors. Do not publish Bitrix assets.
- [ ] Wait through at least two 30-second healthcheck intervals, then repeat health, image ID, duplicate count, session-state buckets, and sanitized history state.
- [ ] Store only sanitized checksummed release receipt. No production identifier/content in repository docs.

## Task 8: Final completion decision

**Files:** None.

- [ ] Complete only if local gates, streamed and candidate audit PASS, verified cold-volume backup, candidate provenance, additive migration/schema, health, API/browser smoke, duplicate check, and second health interval all pass.
- [ ] Report limitation: live unlink/relink was not performed; WhatsApp may not expose already-expired history.
- [ ] Report Baileys as durable provider-delivered history only, not exact date-window coverage.
- [ ] Retain predeploy backup and old tag for separately approved recovery; do not restore/start old image.

## Completion Gate

- [ ] OpenWA live image, source digest, and migration evidence match.
- [ ] Bitrix iframe code/ownership/nginx/port remain unchanged.
- [ ] Production WhatsApp remains linked throughout verification.
- [ ] No secret/customer content appears in evidence.
- [ ] Rollback path is documented but not executed.
