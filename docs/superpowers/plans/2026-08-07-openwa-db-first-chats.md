# OpenWA Database-First Chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Make persisted chats and message threads readable from OpenWA database while linked phone is offline or history import is partial, with stable cursor pagination and durable live updates.

**Architecture:** Backend builds chat list from persisted messages, folds only proven JID/LID aliases, and optionally enriches matching rows from a READY engine. Message endpoint offers snapshot-bound `(createdAt,id)` cursor pages. Dashboard consumes database pages only through React Query infinite cache; persisted socket events update those pages after commit. All live-only actions are gated by READY state.

**Tech Stack:** NestJS 11, TypeORM, React 19, TanStack Query 5, TypeScript 6, Node test runner, Jest 30.

## Global Constraints

- Execute after Tasks 1, 2, 3, and 7 of `2026-08-07-openwa-history-sync-core.md`; reuse its additive index, accepted-engine registry, and persistence fence.
- Preserve existing user WIP. Do not edit `openwa/dashboard/src/components/chats/ChatSidebar.tsx`, `openwa/dashboard/src/a7-embedded.css`, or locale files.
- Changes in `ChatThread.tsx`, `services/api.ts`, and `utils/chatMessages.ts` must retain current search, vCard, poll, call, quote, reaction, media, and status fields.
- Never guess digits for an unresolved `@lid`; keep it as a distinct fail-closed chat until persisted mapping exists.
- Keep offset message API compatible. Dashboard uses cursor mode.
- Run each named failing test before implementation and confirm failure is relevant.

---

## Task 1: Make JID/LID alias resolution durable offline

**Files:**

- Modify: `openwa/src/engine/identity/lid-mapping-store.service.ts`
- Modify: `openwa/src/engine/identity/lid-mapping-store.spec.ts`
- Modify: `openwa/src/modules/message/message.service.ts`
- Modify: `openwa/src/modules/message/message.service.spec.ts`

- [ ] Add mapping-store tests where mappings have been evicted from its in-memory LRU but remain in database. Assert phone-to-LID and LID-to-phone resolution still returns persisted values.
- [ ] Add message-service tests proving `@c.us`, `@s.whatsapp.net`, and a persisted mapped `@lid` produce one query candidate set while an unknown LID stays isolated.
- [ ] Run `cd openwa && npm test -- --runInBand engine/identity/lid-mapping-store.spec.ts modules/message/message.service.spec.ts`; expect new offline assertions to fail.
- [ ] Add async APIs:

```ts
getPersistedPhones(lids: readonly string[]): Promise<Map<string, string>>;
getPersistedLids(phones: readonly string[]): Promise<Map<string, string[]>>;
```

- [ ] Implement bounded `IN (...)` TypeORM queries using normalized bare user parts. Keep current synchronous `getCached()` and `lidsForPhone()` hot paths unchanged.
- [ ] Make `MessageService.resolveJidCandidates()` async and use persisted mappings for reads. Preserve raw unknown LID and never derive a phone from its digits.
- [ ] Rerun both specs; expect pass.
- [ ] Stage only files listed in Task 1, then commit `fix(openwa): resolve chat aliases from durable mappings`.

## Task 2: Build stored chat list without an engine or global scan cap

**Files:**

- Create: `openwa/src/modules/session/stored-chat-list.query.ts`
- Create: `openwa/src/modules/session/stored-chat-list.query.spec.ts`
- Modify: `openwa/src/modules/session/chat-list-overlay.ts`
- Modify: `openwa/src/modules/session/chat-list-overlay.spec.ts`
- Modify: `openwa/src/modules/session/session.service.ts`
- Modify: `openwa/src/modules/session/session.service.spec.ts`
- Modify: `openwa/src/modules/session/session.controller.ts`
- Modify: `openwa/src/modules/session/session.controller.spec.ts`
- Modify: `openwa/src/modules/session/session.module.ts`

- [ ] Add query tests with more than 4,000 total rows, multiple rows per raw chat, equal timestamps, null legacy timestamps, and limit/offset. Assert newest describable row per raw `chatId` is selected without truncating older chats.
- [ ] Add overlay tests: DB-only list, DB row absent from live list, known alias collapse, unknown LID split, `chatName` fallback, timestamp fallback, deterministic tie, and matching-only live enrichment.
- [ ] Add service/controller tests proving no engine and `syncProgress < 100` still return stored chats; READY engine enriches but cannot add/remove base rows; pagination remains deterministic.
- [ ] Run the four focused specs; expect failures because current service requires engine, rejects partial sync, and scans 4,000 rows.
- [ ] Implement query result:

```ts
interface StoredChatSeed {
  rawChatId: string;
  messageId: string;
  preview: string;
  chatName: string | null;
  timestamp: number | null;
  createdAt: Date;
}
```

- [ ] Use database window/subquery semantics supported by SQLite and PostgreSQL to select newest `(createdAt,id)` row per raw chat. Apply canonical folding in TypeScript after persisted LID mapping lookup; choose newest effective `timestamp ?? createdAt`, then stable message ID.
- [ ] Refactor overlay module into pure `buildStoredChats()` and `enrichStoredChats()`. Base fields come from DB: canonical ID, `chatName || canonicalId`, `chatKind()`, group flag, newest preview/timestamp, unread default 0. Live enrichment updates only existing canonical rows.
- [ ] Remove `CHAT_LIST_MESSAGE_SCAN`, engine-required error, and partial-sync conflict from `SessionService.getChats()`. Always build DB base; call `engine.getChats()` only through accepted registry when READY.
- [ ] Update Swagger docs: persisted chats are readable disconnected/partial; remove obsolete 400/409 behavior claims.
- [ ] Rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 2, then commit `feat(openwa): serve chat list from stored messages`.

## Task 3: Make live rows win durably before dispatch

**Files:**

- Create: `openwa/src/modules/session/message-live-upsert.ts`
- Create: `openwa/src/modules/session/message-live-upsert.spec.ts`
- Create: `openwa/src/modules/session/session-live-persistence-queue.ts`
- Create: `openwa/src/modules/session/session-live-persistence-queue.spec.ts`
- Modify: `openwa/src/modules/session/message-projector.service.ts`
- Modify: `openwa/src/modules/session/message-history-projector.ts`
- Modify: `openwa/src/modules/session/message-projector.service.spec.ts`
- Modify: `openwa/src/modules/session/session-engine-lifecycle.service.ts`
- Modify: `openwa/src/modules/session/session.module.ts`

- [ ] Add tests for history-first/live-second richness, live-first/history-ignore, preservation of valid fields omitted by live payload, media/status/chat-name upgrades, poll/vCard/quote/reaction preservation, and idempotent duplicate live events.
- [ ] Add queue tests proving FIFO per session, immediate write plus `2000/5000/15000` retries, generation-token cancellation, delete drain, 500-event/16-MiB bounds, and exhausted/overflow signal. A database error causes no WebSocket, hook, webhook, automation, or chat-cache event before commit.
- [ ] Run the upsert/projector specs; expect failures under current insert-ignore/fire-and-forget behavior.
- [ ] Implement a transaction-scoped helper keyed by `(sessionId, waMessageId)`:

```ts
interface LiveUpsertResult {
  row: Message;
  outcome: 'created' | 'updated' | 'unchanged';
}
```

- [ ] Merge precedence: live non-empty body/media/chatName/status fields replace history values; existing valid fields survive when live payload omits them; live arrival never erases poll, vCard body, quote, reactions, call metadata, or archived-media locator.
- [ ] Implement `SessionLivePersistenceQueue.enqueue(sessionId, generationToken, eventKey, writeAndDispatch)`. Serialize writes per session, dedupe queued event keys, account serialized bytes, and track every attempt through core persistence fence. On success remove item and continue. On revoked generation/delete cancel without dispatch.
- [ ] Route `persistInboundMessage()` and `handleOwnSendEcho()` through queue/helper. Commit transaction first, then dispatch all downstream effects from durable row for created/meaningfully updated outcomes; unchanged duplicates do not redispatch. Suppress transient UI on failure.
- [ ] After three failed retries or capacity overflow, revoke and force-stop that engine generation through a narrow lifecycle callback, then let normal same-phone reconnect/history overlap recover the unchanged range. Persist sanitized sync failure; never advance checkpoint or keep accepting unpersisted live events.
- [ ] Keep history projector insert-ignore on existing live row and persist history `chatName` when present.
- [ ] Rerun focused specs; expect pass.
- [ ] Stage only files listed in Task 3, then commit `fix(openwa): persist live message precedence before dispatch`.

## Task 4: Add snapshot-bound cursor message API

**Files:**

- Create: `openwa/src/modules/message/message-cursor.ts`
- Create: `openwa/src/modules/message/message-cursor.spec.ts`
- Create: `openwa/src/modules/message/message-history-pagination.spec.ts`
- Modify: `openwa/src/modules/message/message.service.ts`
- Modify: `openwa/src/modules/message/message.service.spec.ts`
- Modify: `openwa/src/modules/message/message.controller.ts`
- Create: `openwa/src/modules/message/message.controller.spec.ts`

- [ ] Test opaque cursor encode/decode, schema version, malformed/base64-garbage input, limit validation, cross-session/chat reuse, and canonical-chat binding. Invalid cursor returns HTTP 400 without querying messages.
- [ ] Add in-memory SQLite pagination tests for equal timestamps and a concurrent newer insert between page 1/page 2; assert every snapshot row appears exactly once with no gap/duplicate and new row does not shift old pages.
- [ ] Run cursor/service/controller/integration specs; expect failures because current endpoint is offset-only and orders by `createdAt` alone.
- [ ] Implement cursor payload and response:

```ts
interface MessageCursorV1 {
  v: 1;
  sessionId: string;
  canonicalChatId: string;
  snapshot: { createdAt: string; id: string };
  before: { createdAt: string; id: string };
}

interface MessagePage {
  messages: Message[];
  total: number;
  nextCursor: string | null;
  hasMore: boolean;
}
```

- [ ] Extend `GetMessagesOptions` with `pagination?: 'cursor'` and `cursor?: string`. `pagination=cursor` with no cursor is the unambiguous first cursor page; any supplied cursor also selects cursor mode. First cursor page captures newest tuple as snapshot; every page constrains `row <= snapshot` and strictly `row < before`, orders `createdAt DESC, id DESC`, requests `limit + 1`, and derives `nextCursor` from last returned row.
- [ ] Resolve aliases from Task 1 before query. Bind cursor to session and canonical chat so it cannot be replayed elsewhere.
- [ ] Keep existing offset branch and `total` field behavior for clients without cursor mode. Add `pagination=cursor` plus optional `cursor` query params and response docs in controller; reject `pagination=cursor` combined with nonzero offset.
- [ ] Rerun all four specs; expect pass.
- [ ] Stage only files listed in Task 4, then commit `feat(openwa): paginate stored messages with stable cursors`.

## Task 5: Convert dashboard thread cache to DB-only infinite pages

**Files:**

- Modify: `openwa/dashboard/src/services/api.ts`
- Modify: `openwa/dashboard/src/hooks/useChatMessages.ts`
- Modify: `openwa/dashboard/src/utils/chatMessages.ts`
- Modify: `openwa/dashboard/src/utils/chatMessages.test.ts`
- Modify: `openwa/dashboard/src/queries.ts`

- [ ] Add pure-helper tests for flattening pages, cross-page dedupe, ascending renderer sort, newest-page live insertion, live field/status precedence, update/remove across pages, and preservation of poll/media/vCard/quote/reaction/call fields.
- [ ] Run `cd openwa/dashboard && npm test -- --test-name-pattern chatMessages`; expect failures for paged structures.
- [ ] Add dashboard API types:

```ts
export interface MessagePage {
  messages: StoredMessage[];
  total: number;
  nextCursor: string | null;
  hasMore: boolean;
}
```

- [ ] Change `getChatMessages(sessionId, chatId, {limit,pagination,cursor,offset,signal})` to return `MessagePage`. Dashboard always sends `pagination: 'cursor'`, including its cursor-less first page. Retain public `getChatHistory()` and `EngineHistoryMessage` for compatibility, but remove its use from chat-page data flow.
- [ ] Convert `useChatMessages()` to `useInfiniteQuery<MessagePage>` using DB endpoint only, `nextCursor` as page param, and request abort signal. Query key must include session and canonical chat.
- [ ] Return flattened/deduped/ascending messages plus `fetchNextPage`, `hasNextPage`, and `isFetchingNextPage`.
- [ ] Implement `InfiniteData<MessagePage>` mutations keyed by `waMessageId ?? id`; never create cache for a thread never opened.
- [ ] Rerun chatMessages tests and dashboard typecheck; expect pass.
- [ ] Stage only files listed in Task 5, then commit `feat(dashboard): read stored messages as cursor pages`.

## Task 6: Keep disconnected sessions readable and live actions disabled

**Files:**

- Modify: `openwa/dashboard/src/pages/Chats.tsx`
- Modify: `openwa/dashboard/src/components/chats/ChatComposer.tsx`
- Modify surgically: `openwa/dashboard/src/components/chats/ChatThread.tsx`
- Modify: `openwa/dashboard/src/hooks/useChatScrollPosition.ts`
- Modify: `openwa/dashboard/src/hooks/useChatScrollPosition.test.ts`
- Modify: `openwa/dashboard/src/utils/scrollDecision.ts`
- Modify: `openwa/dashboard/src/utils/scrollDecision.test.ts`
- Create: `openwa/dashboard/src/pages/Chats.test.ts`
- Modify if canonical reducer behavior changes: `openwa/dashboard/src/utils/chatList.ts`
- Modify if canonical reducer behavior changes: `openwa/dashboard/src/utils/chatList.test.ts`

- [ ] Add page tests: READY/DISCONNECTED/CREATED/ACTION_REQUIRED bound sessions visible regardless of `syncProgress`; partial stored rows render with incomplete indicator; dashboard never calls live history endpoint; offline composer/reply/react/delete/mark-read/profile/channel actions disabled.
- [ ] Add tests for top-of-thread older-page fetch, prepend scroll anchoring, chat switch during in-flight request, stale page isolation, and socket update into active infinite cache.
- [ ] Run dashboard page/scroll/chat-list tests; expect failures under READY+100-only filtering and flat-array cache.
- [ ] In `Chats.tsx`, derive:

```ts
const readable = Boolean(session.phone) &&
  ['ready', 'disconnected', 'created', 'action_required'].includes(session.status);
const liveReady = session.status === 'ready';
```

- [ ] Keep import progress as a non-blocking incomplete indicator. Gate every engine-only query/mutation and composer by `liveReady`; stored list/thread queries remain enabled for readable sessions.
- [ ] Replace direct flat-cache mutations in `Chats.tsx` and `ChatComposer.tsx` with Task 5 page helpers.
- [ ] Add `liveReady/disabled` to composer. Add `hasOlder`, `loadingOlder`, `onLoadOlder`, and `liveActionsEnabled` to thread. Touch only props, scroll trigger, and action controls in `ChatThread.tsx`; retain current vCard/poll rendering blocks byte-for-byte where practical.
- [ ] Extend scroll hook with prepend anchor: after older page arrives, set `scrollTop += newScrollHeight - oldScrollHeight`. Capture session/chat key and ignore completion if user switched.
- [ ] Rerun dashboard tests, typecheck, lint, and build; expect pass.
- [ ] Stage only files listed in Task 6, then commit `feat(dashboard): browse persisted chats while offline`.

## Task 7: Verify backend/dashboard integration and WIP preservation

**Files:**

- Modify only if integration exposes regressions: files from Tasks 1-6.

- [ ] Run backend focused suite:

```powershell
cd openwa
npm test -- --runInBand `
  engine/identity/lid-mapping-store.spec.ts `
  modules/session/stored-chat-list.query.spec.ts `
  modules/session/chat-list-overlay.spec.ts `
  modules/session/message-live-upsert.spec.ts `
  modules/session/session-live-persistence-queue.spec.ts `
  modules/session/message-projector.service.spec.ts `
  modules/message/message-cursor.spec.ts `
  modules/message/message-history-pagination.spec.ts `
  modules/message/message.service.spec.ts `
  modules/message/message.controller.spec.ts `
  modules/session/session.service.spec.ts `
  modules/session/session.controller.spec.ts
```

- [ ] Run dashboard suite:

```powershell
cd openwa/dashboard
npm test
npm run typecheck
npm run lint
npm run build
```

- [ ] Run `cd openwa && npm run lint && npm run build:all`; expect all exit 0.
- [ ] Compare `git diff 9c0e1dd -- openwa/dashboard/src/components/chats/ChatSidebar.tsx openwa/dashboard/src/a7-embedded.css openwa/dashboard/src/i18n/locales`; expect no plan-created changes.
- [ ] Inspect `ChatThread.tsx`, `api.ts`, and `chatMessages.ts` diff and confirm vCard/poll/search/media/quote/reaction/call fields remain represented.
- [ ] Commit any test-only reconciliation as `test(openwa): verify database-first chat flow`.

## Completion Gate

- [ ] DB-only chat list works with no loaded engine and during partial import.
- [ ] Live metadata cannot erase DB-only rows or introduce live-only rows.
- [ ] Stored thread uses one DB source plus post-commit socket updates; no live-history merge remains.
- [ ] Equal timestamps and concurrent insert pagination show no duplicates/gaps.
- [ ] Offline sessions are readable; every live-only action stays disabled until accepted READY engine exists.
- [ ] Continue to `2026-08-07-openwa-safe-live-release.md`; do not mutate production from this plan.
