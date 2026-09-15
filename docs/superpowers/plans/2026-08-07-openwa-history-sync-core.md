# OpenWA Lossless History Sync Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Make a new whatsapp-web.js link durably import its anchored last 10 days, make a same-phone reconnect resume from its last successful checkpoint for any gap, and reject identity/race conditions without advancing or corrupting stored history.

**Architecture:** Put every engine generation behind a bounded identity-acceptance gate. After acceptance, one coordinator owns history cutoff, awaited persistence, retry budget, progress, and a compare-and-set checkpoint. A per-session persistence fence retires and drains writes before deletion. Baileys awaits provider-delivered history but does not advertise exact date-window coverage.

**Tech Stack:** NestJS 11, TypeScript 6, TypeORM, SQLite/PostgreSQL, whatsapp-web.js 1.34, Baileys 7 RC, Jest 30.

## Global Constraints

- Work in an isolated git worktree created from commit `9c0e1dd`; do not stash, reset, or overwrite current dirty files.
- Reconcile only intentional implementation diffs back into the user's working tree after tests pass.
- Preserve all existing message mapping, poll, vCard, search, Bitrix, Django, and n8n behavior.
- Do not edit `openwa/dashboard/src/i18n/locales/*`.
- Migration is additive only: nullable columns and one index. No row rewrite, delete, phone clear, or production down-migration.
- Exact 10-day/arbitrary-gap promise applies only to `whatsapp-web.js`; Baileys remains provider-controlled.
- Never log phone numbers, message bodies, API keys, credentials, or serialized buffered events.
- Run each named failing test before implementation, confirm failure is caused by missing behavior, then implement minimum code and rerun.

---

## Task 1: Add durable schema, configuration, and API state

**Files:**

- Create: `openwa/src/database/migrations/1786300000000-AddLosslessHistorySyncState.ts`
- Create: `openwa/src/database/migrations/__tests__/1786300000000-AddLosslessHistorySyncState.spec.ts`
- Modify: `openwa/src/modules/session/entities/session.entity.ts`
- Modify: `openwa/src/modules/message/entities/message.entity.ts`
- Modify: `openwa/src/modules/session/dto/session-response.dto.ts`
- Modify: `openwa/src/modules/infra/migration-tables.types.ts`
- Modify: `openwa/src/modules/infra/table-importers.ts`
- Modify: `openwa/src/modules/infra/infra-data.controller.ts`
- Modify: `openwa/src/modules/infra/infra-data.controller.spec.ts`
- Modify: `openwa/src/config/configuration.ts`
- Modify: `openwa/src/config/configuration.spec.ts`
- Modify: `openwa/src/config/env.validation.ts`
- Modify: `openwa/src/config/env.validation.spec.ts`
- Modify: `openwa/src/config/env-precedence.ts`
- Modify: `openwa/docker-compose.yml`

- [ ] Write migration tests for SQLite and PostgreSQL SQL generation: three nullable session columns, `(sessionId, chatId, createdAt)` message index, and a non-destructive `up()`.
- [ ] Run `cd openwa && npm test -- --runInBand database/migrations/__tests__/1786300000000-AddLosslessHistorySyncState.spec.ts`; expect failure because migration does not exist.
- [ ] Add nullable entity fields:

```ts
historyFirstLinkedAt!: Date | null;
historySyncToken!: string | null;
historySyncError!: string | null;
```

- [ ] Add message entity index `@Index(['sessionId', 'chatId', 'createdAt'])` without changing the existing unique `(sessionId, waMessageId)` constraint.
- [ ] Implement migration `up()` with portable TypeORM table/index operations. Implement `down()` only for local development; release procedure must never run it on production.
- [ ] Include all three session fields in infra export/import allowlists so backup transport preserves them. Exclude `historySyncToken` from public DTO serialization and expose `historySyncError` as sanitized `syncError`.
- [ ] Add validated config `engine.wwebjsHistoryMaxMessagesPerChat`, sourced from `WWEBJS_HISTORY_MAX_MESSAGES_PER_CHAT`, positive integer, default `50000`. Add compose forwarding and blank-env precedence entry.
- [ ] Rerun migration, config, env, and infra controller specs; expect pass.
- [ ] Stage only files listed in Task 1, then commit `feat(openwa): persist lossless history sync state`.

## Task 2: Normalize owner identity and gate engine generations

**Files:**

- Modify: `openwa/src/engine/identity/wa-id.ts`
- Modify: `openwa/src/engine/identity/wa-id.spec.ts`
- Modify: `openwa/src/engine/engine-registry.service.ts`
- Modify: `openwa/src/engine/engine-registry.service.spec.ts`
- Create: `openwa/src/modules/session/session-engine-acceptance-buffer.ts`
- Create: `openwa/src/modules/session/session-engine-acceptance-buffer.spec.ts`
- Create: `openwa/src/modules/session/session-legacy-identity-audit.ts`
- Create: `openwa/src/modules/session/session-legacy-identity-audit.spec.ts`
- Create: `openwa/src/modules/session/session-identity-guard.ts`
- Create: `openwa/src/modules/session/session-identity-guard.spec.ts`
- Create: `openwa/test/fixtures/legacy-identity-audit.json`
- Modify: `openwa/src/modules/session/session.module.ts`

- [ ] Add tests proving `normalizePhoneIdentity()` accepts formatted phone/JID variants, returns digits only, and rejects empty, LID-only, malformed, and non-phone identifiers.
- [ ] Add registry tests proving generation phases are `PENDING -> DRAINING -> READY` or terminal `REVOKED`; public `require()` rejects PENDING/DRAINING, only matching token can transition/revoke, and stale tokens cannot regain access.
- [ ] Add buffer tests for ordered replay, events arriving during drain, and exact limits: 500 events, 16 MiB serialized payload, 30 seconds; drain loops until queue is empty, and every overflow rejects, clears data, and can never drain later.
- [ ] Add identity-guard tests for these transactional classifications:

```ts
type IdentityDecision =
  | { kind: 'FIRST_LINK'; phone: string; firstLinkedAt: Date }
  | { kind: 'SAME_PHONE'; phone: string; firstLinkedAt: Date }
  | { kind: 'QUARANTINE'; reason: 'DIFFERENT_PHONE' | 'LEGACY_AMBIGUOUS' | 'LEGACY_CONFLICT' };
```

- [ ] Add shared golden audit vectors for PASS, FAIL, and INCONCLUSIVE. Test account-side extraction from `incoming.to` and `outgoing.from`, `@c.us`/`@s.whatsapp.net` normalization, persisted LID mapping, missing/unparseable sides, bound/current mismatch, and multiple historical owners. Result objects contain reason classes and counts, never identity/message values.
- [ ] Cover new empty session, null-phone/no-history session with existing credentials, normalized same phone, different phone, null-phone with checkpoint, null-phone with messages, bound phone with null checkpoint, and persisted LID evidence. Confirm only empty-history cases may first-link and quarantine preserves phone/checkpoint/messages.
- [ ] Run the five focused specs; expect failures for missing APIs.
- [ ] Implement `normalizePhoneIdentity()` using explicit WhatsApp phone dialects and digit normalization; never guess a phone from `@lid`.
- [ ] Extend `EngineRegistry` with `beginGeneration`, `acceptForDrain`, `publishGeneration`, `revokeGeneration`, `isAcceptedToken`, `getAccepted`, `getLifecycle`, and `tokenFor`. Internal persistence may use the matching accepted token in DRAINING; public `require()`/normal `get()` return READY generations only.
- [ ] Implement `SessionEngineAcceptanceBuffer.begin/defer/startDrain/finishDrain/reject`. Store callbacks, byte estimates, start time, phase, and token per session. While DRAINING, newly arriving events append behind existing events until one atomic empty-queue transition closes the buffer.
- [ ] Implement `SessionLegacyIdentityAudit.classify()` against bound identity, authenticated current identity, stored direct-message owner sides, and persisted LID mappings. Any conflict is FAIL; any required unproven side/mapping/identity is INCONCLUSIVE; only all-proven same-owner evidence is PASS. Identity guard accepts legacy data only on PASS.
- [ ] Implement `SessionIdentityGuard.validateAndBind()` in one database transaction. First link sets normalized `phone` and immutable `historyFirstLinkedAt`. Same phone preserves existing anchor; a legacy bound phone with null anchor/checkpoint sets anchor to session `createdAt` (never later) so retry can over-read but cannot shrink missing history. Mismatch/legacy ambiguity writes `ACTION_REQUIRED` plus durable sanitized `historySyncError` and changes no history ownership fields.
- [ ] Register providers in `session.module.ts` and rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 2, then commit `feat(openwa): gate engine generations by phone identity`.

## Task 3: Buffer all pre-identity events and accepted-engine operations

**Files:**

- Modify: `openwa/src/engine/interfaces/whatsapp-engine.interface.ts`
- Modify: `openwa/src/engine/adapters/wwebjs-host.ts`
- Modify: `openwa/src/engine/adapters/whatsapp-web-js.adapter.ts`
- Modify: `openwa/src/engine/adapters/baileys-lifecycle.ts`
- Modify: `openwa/src/engine/adapters/baileys.adapter.ts`
- Modify: `openwa/src/modules/session/session-engine-event-wiring.ts`
- Modify: `openwa/src/modules/session/session-engine-lifecycle.service.ts`
- Modify: `openwa/src/modules/session/session-engine-leaf-events.ts`
- Modify: `openwa/src/modules/session/session.service.spec.ts`
- Modify: `openwa/src/modules/message/message.service.ts`
- Modify: `openwa/src/modules/message/bulk-message.service.ts`
- Modify: engine-backed services under `openwa/src/modules/{call,catalog,channel,contact,group,label,message,profile,status}/*.service.ts`

- [ ] Add lifecycle tests proving QR/teardown control events remain usable while pending, while READY/authenticated/message/status/contact/group/call/history events are buffered. Before acceptance, no database write, webhook, hook, WebSocket event, engine-backed read, or send occurs.
- [ ] Add mismatch/invalid/overflow tests proving controlled remote unlink is attempted, generation is revoked, forced teardown runs, only that generation's new credentials are purged on unlink failure, no reconnect is scheduled, and old data remains.
- [ ] Run `npm test -- --runInBand modules/session/session.service.spec.ts modules/session/session-engine-acceptance-buffer.spec.ts modules/session/session-identity-guard.spec.ts`; expect new assertions to fail.
- [ ] Change `EngineEventCallbacks.onReady` to return `void | Promise<void>`. Stop adapters from publishing READY before the callback resolves; pending readiness stays internal.
- [ ] Route every data-bearing callback through the phase-aware buffer. After validation, move token to DRAINING for internal persistence, replay in original order, append/replay events that arrive during drain, atomically close only on an empty queue, then publish generation READY for public reads/sends and emit authenticated/READY. This prevents a new live event from overtaking buffered history while public APIs remain unavailable during drain.
- [ ] On mismatch, empty identity, timeout, or buffer overflow: reject buffer first, revoke token, attempt `engine.logout()`, force-destroy if needed, purge generation-local credentials only, persist `ACTION_REQUIRED`, and suppress auto-reconnect.
- [ ] Replace engine access in message/bulk and all listed live services with accepted-registry access. Preserve lifecycle raw access only in start/stop/logout/delete/recovery code.
- [ ] Remove phone values from readiness logs; log session ID, generation ID, result class, and elapsed milliseconds only.
- [ ] Rerun lifecycle/service specs; expect pass.
- [ ] Stage only files listed in Task 3, then commit `feat(openwa): buffer events until identity acceptance`.

## Task 4: Make history delivery awaited end to end

**Files:**

- Modify: `openwa/src/engine/interfaces/whatsapp-engine.interface.ts`
- Modify: `openwa/src/engine/adapters/wwebjs-host.ts`
- Modify: `openwa/src/engine/adapters/wwebjs-history.ts`
- Create: `openwa/src/engine/adapters/wwebjs-history.spec.ts`
- Modify: `openwa/src/engine/adapters/baileys-history.ts`
- Modify: `openwa/src/engine/adapters/baileys-lifecycle.ts`
- Modify: `openwa/src/engine/adapters/baileys-events.spec.ts`
- Modify: `openwa/src/modules/session/session-engine-event-wiring.ts`
- Modify: `openwa/src/modules/session/message-history-projector.ts`
- Modify: `openwa/src/modules/session/message-projector.service.spec.ts`

- [ ] Change the callback contract to `onHistoryMessages?: (messages: IncomingMessage[]) => void | Promise<void>`.
- [ ] Add rejection tests at every producer boundary: whatsapp-web.js batch, Baileys `messaging-history.set`, event wiring, and `MessageHistoryProjector`. Assert DB rejection reaches caller and no completion callback/checkpoint follows.
- [ ] Run the four focused specs; expect rejection assertions to fail because current paths fire-and-forget.
- [ ] Return the projector promise from event wiring; remove `.catch()` logging that converts failure to success.
- [ ] Await callbacks in `WwebjsHistory` and `BaileysHistory`; let failures propagate. Preserve Baileys provider-controlled scope and contact-name harvesting.
- [ ] Store `chatName` supplied by history while retaining insert-ignore on `(sessionId, waMessageId)` collisions.
- [ ] Rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 4, then commit `fix(openwa): await durable history persistence`.

## Task 5: Replace the 4,000 cap with a complete whatsapp-web.js reader

**Files:**

- Modify: `openwa/src/engine/adapters/wwebjs-history.ts`
- Modify: `openwa/src/engine/adapters/wwebjs-history.spec.ts`
- Modify: `openwa/src/engine/adapters/whatsapp-web-js.adapter.ts`
- Modify: `openwa/src/engine/types/whatsapp-web-js.types.ts`

- [ ] Add deterministic tests for prefixes `100, 200, 400, ...`, cutoff reached, exhaustion proven by returned count, eligible chat with more than 4,000 messages, 50/60-day synthetic gaps, unique-ID batch emission, stable-order release, and three stable chat-set passes.
- [ ] Add failure tests for non-advancing prefixes, missing message IDs, mapper failures, unsupported vs accidental errors, chat retry delays `2000/5000/15000`, evaluation timeout, continued chat-set churn, and 50,000 resource ceiling.
- [ ] Run `npm test -- --runInBand engine/adapters/wwebjs-history.spec.ts`; expect failures under current fixed-cap implementation.
- [ ] Implement typed failures:

```ts
type HistoryReadFailure =
  | 'CHAT_READ_FAILED'
  | 'MAPPING_FAILED'
  | 'MISSING_MESSAGE_ID'
  | 'NON_ADVANCING_PREFIX'
  | 'EVALUATION_TIMEOUT'
  | 'CHAT_SET_UNSTABLE'
  | 'RESOURCE_LIMIT';
```

- [ ] For each supported chat, call `fetchMessages({limit})` with a growing prefix, keep a `Set` of emitted IDs, emit only new mapped rows, and discard fetched arrays after each awaited batch. Finish only when oldest eligible timestamp reaches cutoff or a smaller-than-requested result proves exhaustion.
- [ ] Sanction only explicit status/newsletter/broadcast/group/system/ephemeral exclusions and records older than cutoff. Treat all unexpected reads/mapping omissions as failures.
- [ ] Re-enumerate chat IDs after each pass; process additions through three stable-set passes. Fail the run if the set still changes.
- [ ] Surface evaluation timeout as tainted-generation metadata; never start another page evaluation on that generation.
- [ ] Rerun adapter specs; expect pass.
- [ ] Stage only files listed in Task 5, then commit `fix(openwa): read whatsapp history to cutoff`.

## Task 6: Coordinate cutoff, CAS checkpoint, retries, and circuit breakers

**Files:**

- Create: `openwa/src/modules/session/session-history-cas.ts`
- Create: `openwa/src/modules/session/session-history-cas.spec.ts`
- Create: `openwa/src/modules/session/history-retry-policy.ts`
- Create: `openwa/src/modules/session/history-retry-policy.spec.ts`
- Create: `openwa/src/modules/session/session-history-sync-coordinator.ts`
- Create: `openwa/src/modules/session/session-history-sync-coordinator.spec.ts`
- Modify: `openwa/src/modules/session/session-engine-lifecycle.service.ts`
- Modify: `openwa/src/modules/session/session-engine-controls.ts`
- Modify: `openwa/src/modules/session/session.module.ts`
- Modify: `openwa/src/modules/session/session.service.spec.ts`

- [ ] Test cutoff calculation: first link always uses immutable `historyFirstLinkedAt - 10 days`; reconnect uses `historyImportedAt - 1 day`; 2/50/60-day gaps all retain the same starting checkpoint until full success; restart retains failed first-link cutoff.
- [ ] Test one active run per session, duplicate READY coalescing, progress from completed chats only, full-run retry delays `5000/30000/120000`, fourth settled failure circuit, three timeout-generation replacements, operator Start budget reset, and stop/logout/disconnect cancellation.
- [ ] Test `HistoryRunGuard` CAS against session ID, normalized phone, starting checkpoint, READY status, owner node, and `historySyncToken`. Stale stop, replacement engine, changed owner, changed phone, or changed checkpoint must update zero rows.
- [ ] Run the three new specs plus session service spec; expect missing coordinator failures.
- [ ] Implement coordinator API:

```ts
onAcceptedGeneration(sessionId: string, generationToken: string): Promise<void>;
cancelAndRotate(sessionId: string): Promise<void>;
retireAndDrain(sessionId: string): Promise<void>;
```

- [ ] On run start, generate/store token with guarded update and set progress 0. Await complete engine import. On success, atomically CAS `historyImportedAt = runStartedAt`, `syncProgress = 100`, `historySyncError = null`, and clear token. On failure leave checkpoint unchanged and progress below 100.
- [ ] Ordinary failure stores a sanitized class, schedules unchanged-range retry, and never overwrites identity/quarantine errors. Resource ceiling and exhausted budgets stop engine and persist `ACTION_REQUIRED`.
- [ ] Timeout immediately revokes token/buffer, force-stops tainted generation, then lets existing reconnect scheduler create and revalidate a fresh generation. Late work must fail persistence/CAS gates.
- [ ] Emit structured import logs with session ID, generation ID, attempt, completed/total chat counts, progress, and sanitized failure class only. Never include phone, chat/message ID, body, credentials, or serialized event data.
- [ ] Replace lifecycle `historyRunning`/`importHistory` logic with coordinator calls and register provider.
- [ ] Rerun coordinator/lifecycle specs; expect pass.
- [ ] Stage only files listed in Task 6, then commit `feat(openwa): coordinate resumable history imports`.

## Task 7: Fence live/history writes and drain deletion

**Files:**

- Create: `openwa/src/modules/session/session-persistence-fence.service.ts`
- Create: `openwa/src/modules/session/session-persistence-fence.service.spec.ts`
- Modify: `openwa/src/modules/session/message-projector.service.ts`
- Modify: `openwa/src/modules/session/message-history-projector.ts`
- Modify: `openwa/src/modules/session/message-mutation-projector.ts`
- Modify: `openwa/src/modules/session/session-engine-leaf-events.ts`
- Modify: `openwa/src/modules/session/session-engine-event-wiring.ts`
- Modify: `openwa/src/modules/session/session-engine-controls.ts`
- Modify: `openwa/src/modules/session/session.service.ts`
- Modify: `openwa/src/modules/session/logout-teardown-race.spec.ts`
- Modify: `openwa/src/modules/session/message-projector.service.spec.ts`

- [ ] Test `run/track/isRetired/retireAndDrain`: no new work after retirement, all tracked promises settle before drain returns, rejected work is observed, and a retired session cannot be reopened by a stale generation.
- [ ] Add race tests: history insert versus stop, live insert versus delete, checkpoint CAS versus delete, and late page evaluation versus deletion. Assert no orphan rows can appear after transaction deletion.
- [ ] Run focused fence/projector/logout specs; expect failures.
- [ ] Wrap inbound, own-send echo, status, history, mutation, and leaf-event persistence with generation acceptance plus persistence fence tracking.
- [ ] Change deletion order to: mark stopping/retired, rotate history token, reject buffer, revoke engine, cancel retries, teardown engine, await persistence drain, transactionally delete dependent/session rows, purge credentials, clear registries.
- [ ] Keep history insert unique-conflict behavior; do not introduce a second message-ownership column.
- [ ] Rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 7, then commit `fix(openwa): drain persistence before session deletion`.

## Task 8: Preserve identity and checkpoint through logout/startup

**Files:**

- Modify: `openwa/src/modules/session/session-engine-controls.ts`
- Modify: `openwa/src/modules/session/session.service.ts`
- Modify: `openwa/src/modules/session/session-error-store.service.ts`
- Modify: `openwa/src/modules/session/session-status-broadcaster.ts`
- Modify: `openwa/src/modules/session/logout-teardown-race.spec.ts`
- Modify: `openwa/src/modules/session/session.service.spec.ts`

- [ ] Rewrite logout tests first: success preserves phone/checkpoint/messages and ends `CREATED`; incomplete unlink preserves them, writes durable reason, ends `ACTION_REQUIRED`; neither auto-starts at boot; explicit Start allows QR but still enforces same-phone validation.
- [ ] Add restart tests proving `ACTION_REQUIRED` is not rewritten to `DISCONNECTED`. Add error-precedence tests for identity quarantine, sync failure, incomplete logout, explicit Start, validated reconnect, and successful import.
- [ ] Run logout/startup focused specs; expect current phone-clearing assertions to fail.
- [ ] Remove every logout update that writes `{phone: null, historyImportedAt: null}`. Rotate/clear generation token before teardown. Success writes `CREATED`; incomplete logout writes `ACTION_REQUIRED` and sanitized durable `historySyncError`.
- [ ] Restrict boot auto-start to previously authenticated `DISCONNECTED` sessions. Never auto-start `CREATED` or `ACTION_REQUIRED`.
- [ ] Make public session error resolution prefer durable identity/legacy quarantine, then logout-incomplete, then ordinary sync; clear each only at its specified validated transition.
- [ ] Rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 8, then commit `fix(openwa): preserve history state across logout`.

## Task 9: Prove core contract end to end

**Files:**

- Create: `openwa/src/modules/session/lossless-history-sync.integration.spec.ts`
- Modify only if failures identify regressions: focused production files from Tasks 1-8.

- [ ] Build an in-memory SQLite integration fixture with fake accepted engines and controlled clocks. Cover all core verification items: anchored first 10 days, same-phone 2/50/60-day resumes, >4,000 messages, DB rejection, crash/restart, mismatch, ambiguous legacy state, buffer limits, timeout replacement, stable retries, CAS races, logout states, and deletion drain.
- [ ] Run:

```powershell
cd openwa
npm test -- --runInBand `
  database/migrations/__tests__/1786300000000-AddLosslessHistorySyncState.spec.ts `
  engine/identity/wa-id.spec.ts `
  engine/engine-registry.service.spec.ts `
  engine/adapters/wwebjs-history.spec.ts `
  engine/adapters/baileys-events.spec.ts `
  modules/session/session-engine-acceptance-buffer.spec.ts `
  modules/session/session-identity-guard.spec.ts `
  modules/session/session-history-cas.spec.ts `
  modules/session/history-retry-policy.spec.ts `
  modules/session/session-history-sync-coordinator.spec.ts `
  modules/session/session-persistence-fence.service.spec.ts `
  modules/session/message-projector.service.spec.ts `
  modules/session/logout-teardown-race.spec.ts `
  modules/session/lossless-history-sync.integration.spec.ts `
  modules/session/session.service.spec.ts
```

- [ ] Run `npm run lint`, `npm run build`, and `npm run test:pg-smoke`; all must exit 0.
- [ ] Run full `npm test -- --runInBand`; classify any pre-existing failure with evidence and fix only regressions caused by this plan.
- [ ] Review logs in tests to confirm no phone/message/credential values appear.
- [ ] Stage only Task 9 integration/reconciliation files, then commit `test(openwa): prove lossless history sync contract`.

## Completion Gate

- [ ] Compare implementation against every locked rule in `docs/superpowers/specs/2026-08-07-openwa-lossless-history-sync-design.md`.
- [ ] Confirm migration contains no destructive SQL and token never appears in API/export logs.
- [ ] Confirm all accepted-engine consumers are gated; lifecycle-only raw lookups are documented at call sites.
- [ ] Confirm exact-window wording remains whatsapp-web.js-only.
- [ ] Do not deploy from this plan alone. Continue with DB-first chats plan, then safe release plan.
