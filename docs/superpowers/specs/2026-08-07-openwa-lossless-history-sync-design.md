# OpenWA Lossless History Sync Design

Date: 2026-08-07  
Status: Approved by user; implementation planning

## Goal

Make OpenWA history predictable and loss-resistant:

- A newly created session imports the latest 10 days available from WhatsApp.
- A previously bound session reconnecting the same phone imports every available message since its last safe checkpoint, whether the gap is 2, 50, 60, or more days.
- Imported chats and messages are persisted before sync is declared complete.
- Stored chats remain visible while WhatsApp is disconnected.
- From this release onward, one session cannot accept data from a second WhatsApp phone identity. Legacy sessions must pass identity audit or remain quarantined.

## Locked product rules

1. One OpenWA session belongs to one normalized WhatsApp phone number for its lifetime.
2. A different phone scanned into an already-bound session is rejected and unlinked. Operator must create a new session.
3. A deliberate logout preserves the bound phone identity, history checkpoint, and stored messages. It removes credentials only.
4. Session deletion remains the only existing operation that removes that session's stored messages.
5. Exact crash/race safety requires one additive OpenWA migration. No existing message or credential data is rewritten or deleted.

## Engine scope

The exact 10-day and arbitrary-gap contract is implemented for `whatsapp-web.js`, the engine used by the live A7 OpenWA stack. Baileys receives provider-controlled history and cannot request an exact date range. Its history callback becomes durable, but the UI/API must not claim this date-window guarantee for Baileys.

## Additive persistence change

Add nullable session columns:

- `historyFirstLinkedAt`: immutable anchor for the first 10-day window.
- `historySyncToken`: random engine-generation token used by conditional checkpoint writes.
- `historySyncError`: durable sanitized sync/identity failure shown after restart.

Add message index `(sessionId, chatId, createdAt)` for DB-first chat grouping. Forward migration only adds nullable columns/index; it performs no row deletion, phone clearing, message rewrite, or production down-migration.

## Identity lifecycle

### First link

A session with no bound phone, no checkpoint, and no stored history may accept the authenticated phone. In one guarded write it stores normalized phone and `historyFirstLinkedAt`. Its cutoff is `historyFirstLinkedAt - 10 days`.

That first-link anchor never moves. A failed run or process restart therefore retries the original 10-day window instead of recalculating from a later day and silently dropping the oldest part.

### Same-phone reconnect

If authenticated phone matches stored phone after digit normalization, session remains bound. Import starts no later than the last successful checkpoint with a one-day overlap. It therefore covers the whole disconnected period and may safely reread an older range. Overlap protects boundary races; unique `(sessionId, waMessageId)` storage removes duplicates.

### Different-phone scan

Phone comparison happens before READY/authenticated events are exposed, before data from that engine generation is trusted, and before history import begins. Empty or unparseable phone identity fails closed.

Each engine generation starts behind an event buffer bounded to 500 events, 16 MiB serialized payload, and 30 seconds. Before acceptance there is no READY/authenticated webhook, WebSocket event, hook, message/status/contact write, engine-backed read, or send. After acceptance buffered events replay in order. Any bound breach rejects and tears down that generation, persists/emits nothing from it, and leaves old phone/checkpoint/data unchanged. Rejected buffers can never replay later.

On mismatch:

- Keep old `phone`, checkpoint, and all message rows unchanged.
- Do not emit READY.
- Perform controlled unlink/teardown of newly scanned companion without automatic reconnect. If remote unlink fails, force-stop engine and purge only that generation's new local credentials.
- Put session into `ACTION_REQUIRED` with a clear reason telling operator to create a new session.

### Legacy ambiguous session

Legacy state is classified before link:

- `phone = null` plus checkpoint or stored messages: ambiguous; preserve data and block reuse.
- `phone = null`, no checkpoint/messages, credentials present: safe to accept first authenticated identity.
- Bound phone plus null checkpoint/partial messages: keep phone; choose conservative first-link anchor no later than session creation, so retry may fetch extra but cannot shrink the missing range.
- Evidence of multiple historical owner identities or conflict with bound phone: quarantine as `ACTION_REQUIRED`; never auto-merge or delete rows.

Old releases did not store phone identity on every message. Pre-deploy audit derives account-side identity from bound session phone, current authenticated phone, and each direct row (`incoming.to`, `outgoing.from`), normalizing `@c.us`/`@s.whatsapp.net` and using only persisted LID mappings. Output contains counts and PASS/FAIL/INCONCLUSIVE only, never phone/message values:

- PASS: every provable account-side identity resolves to bound/current phone and no relevant row is unresolved.
- FAIL: any identity conflicts.
- INCONCLUSIVE: owner side is missing/unparseable, an account-side LID lacks mapping, or current/bound identity cannot be proven.

Pre-deploy FAIL or INCONCLUSIVE stops before any production mutation; current live session must reach PASS before migration/deploy continues. In the upgraded app, any legacy session later classified FAIL/INCONCLUSIVE is quarantined and cannot auto-start or accept QR data. There is no silent override. Strict no-new-mixing behavior is prospective.

### Deliberate logout

Successful or incomplete engine-backed logout keeps `phone` and `historyImportedAt`. A successful logout ends in `CREATED`, which is manually startable but excluded from boot auto-start. An incomplete logout ends in `ACTION_REQUIRED`. `ACTION_REQUIRED` is no longer rewritten to auto-startable `DISCONNECTED` during process boot. Starting either state later allows QR linking, but identity validation still applies.

Transient stop/disconnect keeps current auto-reconnect behavior. Remote handset unlink also keeps the bound identity and only accepts the same phone on the next QR.

## Durable history pipeline

History delivery becomes awaited end to end:

`WhatsApp page read -> adapter batch callback -> session wiring -> durable MessageProjector insert -> next batch`

The engine callback contract accepts `void | Promise<void>` for compatibility, and every producer that controls history progression, including whatsapp-web.js and Baileys, awaits its result. Rejection propagates through adapter, event wiring, and projector. A rejected database write fails the import; it can never be logged and ignored while watermark advances.

### Read completeness

- Remove fixed 4,000-message per-chat completion cap.
- Because whatsapp-web.js exposes a growing-prefix `fetchMessages({ limit })` API, double the requested prefix from 100 until oldest timestamp reaches cutoff or returned count proves exhaustion. Persist only newly discovered message IDs each round; release Node-side arrays between rounds.
- Require returned unique count or oldest timestamp to advance. A non-advancing prefix fails instead of looping forever.
- A timed-out Puppeteer evaluation is not cancellable. Timeout therefore taints and force-stops that engine generation before retry; no second evaluation may overlap it.
- Settled chat errors get 3 attempts with 2s/5s/15s delays. Exhaustion fails current run.
- Skip unsupported chat kinds intentionally before expensive reads; never count an accidental timeout/read error as success.
- Sanctioned skips are status/newsletter/broadcast/group/system messages, configured ephemeral exclusions, and records older than cutoff. Missing IDs or unexpected mapping failures inside eligible history fail the chat rather than disappearing silently.
- Re-enumerate chat IDs after the pass. Process newly discovered IDs, up to 3 stable-set passes; continued churn fails run and retries unchanged range.
- Default per-chat growing-prefix safety ceiling is 50,000 messages. Reaching it never counts as complete: abort unchanged range, stop automatic scanning, persist `ACTION_REQUIRED`, and require operator start/resume after raising resources/ceiling. This is a resource circuit breaker, not a history cutoff.

WhatsApp can only provide history still available to the linked client. "Complete" therefore means every eligible chat was read to cutoff or confirmed exhausted, and every offered message was durably processed.

### Checkpoint and progress

- Set `syncProgress` to 0 when a run starts.
- Update progress only from completed chat work.
- Move `historyImportedAt` to run start time only after all reads and database writes succeed.
- On any failure, leave checkpoint unchanged and leave progress below 100.
- After settled failures, retry full unchanged range after 5s, 30s, and 120s while same accepted generation remains READY. A fourth consecutive failed full run opens circuit breaker, stops engine, and sets durable `ACTION_REQUIRED`; operator Start begins a fresh validated generation and resets budget. UI keeps partial data visible.
- Timeout force-stops generation, revokes token/buffer, then existing reconnect scheduler creates a fresh generation. Fresh generation must revalidate same phone before retrying unchanged range. After 3 timeout-driven generation replacements, circuit opens for operator action. Late completion from old Puppeteer work cannot pass revoked persistence gate.
- A restart/READY event also retries from unchanged checkpoint.
- Cancel retries when session stops, changes engine generation, or identity validation fails.

Progress and final checkpoint writes use conditional compare-and-set against session ID, normalized bound phone, starting checkpoint, status, owner, and `historySyncToken`. Stop/logout/disconnect rotates or clears token before teardown, so a stale run cannot win a check-then-await race. Delete retires session, cancels work, and drains tracked history/live persistence promises before deleting message rows; late inserts cannot recreate orphan data.

`historySyncError` precedence: identity/legacy quarantine errors are highest and cannot be overwritten by sync retries. They clear only after explicit operator Start and successful same-phone validation. Ordinary sync error clears atomically only with a successful full import/checkpoint update. Logout-incomplete reason clears only after later validated connection or completed logout. Successful retry therefore cannot leave stale failure UI.

This makes repeated imports safe: old range can be reread, but unique message ID storage prevents duplicate rows.

## Database-first chat experience

### Chat list

`GET /sessions/:id/chats` uses persisted message-backed chats as its base, even when no engine is loaded. It groups identities through existing JID/LID normalization, selects newest stored message per canonical chat, and sorts deterministically by actual message timestamp then stable ID. Existing `chatName` supplies labels with canonical JID fallback; history persistence fills `chatName` when WhatsApp provides it. When engine is READY, live metadata may enrich matching rows; it may not remove DB-only rows. Chats without any eligible stored message are outside this DB guarantee.

### Message thread

Dashboard reads stored message API only. It stops merging a second live-history response into the thread. Existing real-time socket updates still append/update rows after normal persistence.

History insert uses insert-ignore only when a live row already exists. Live arrival uses conflict-aware upsert and wins for richer body/media/chat-name/status metadata while preserving valid fields it does not carry. WebSocket/hook/webhook dispatch happens after durable live upsert. Failed live persistence is tracked and retried; no transient chat row is shown before DB commit, and delete drains this queue too.

Older stored messages use cursor pagination ordered by `(createdAt, id)`, with first-page snapshot boundary, `nextCursor`, and `hasMore`. This prevents gaps/duplicates when live rows arrive between pages or timestamps tie. Existing offset parameters remain for API compatibility, but dashboard uses cursor mode. Changing chats or sessions resets pagination and stale requests cannot update current thread.

`@c.us`, `@s.whatsapp.net`, and a persisted mapped `@lid` resolve to one canonical direct chat and thread. Without a stored LID mapping, raw LID remains a separate fail-closed identity until mapping exists; digits are never guessed. Null legacy timestamps fall back to `createdAt`.

### Disconnected viewing

Chats page permits selection of bound sessions with stored data in READY, DISCONNECTED, CREATED, or ACTION_REQUIRED states. Stored lists and threads remain readable, including safely persisted partial results while `syncProgress < 100`; UI continues to show that sync is incomplete. Sending and live-only actions remain disabled unless engine is READY.

No translation files are changed; existing labels/status presentation are reused.

## Error and race handling

- Engine-generation and identity-accepted checks guard every async identity, live persistence, import, retry, and progress write.
- Concurrent READY events share one import promise per session; no parallel history scans.
- Stop/logout/delete cancels scheduled retries and prevents late completion writes.
- Different-phone rejection cannot clear old phone, checkpoint, or messages even if unlink fails.
- History batch insert retains unique-index conflict handling for live/history races.
- Import logs contain session ID, attempt, chat count, progress, and sanitized failure class; never phone numbers, message bodies, API keys, or credentials.

## Verification

Focused automated tests are written first and cover:

1. First link uses exactly a 10-day cutoff.
2. Same phone preserves identity/checkpoint and accepts normalized formatting.
3. Synthetic 2-, 50-, and 60-day gaps start from checkpoint minus overlap.
4. Successful/incomplete logout preserves phone/checkpoint/data, uses safe terminal states, and avoids boot auto-start.
5. Different phone is rejected before import and old rows remain untouched.
6. Legacy null-phone session with messages fails closed.
7. Pre-identity events are buffered; mismatch/invalid identity emits no READY/auth side effect. Durable reason survives restart.
8. Buffer event/count/time overflow tears down generation, writes/emits nothing, preserves old state, and cannot replay later.
9. History DB rejection prevents checkpoint/progress completion in both history producers.
10. Timeout kills old generation; fresh generation revalidates, retries unchanged range, and late old work cannot write.
11. Stalled/error retry budget and 50,000-message safety ceiling open circuit without advancing checkpoint.
12. One eligible chat with more than 4,000 messages across synthetic 50/60-day gap completes without old cap loss.
13. Complete import awaits every batch and advances checkpoint once; failed first-link retries retain identical cutoff across restart.
14. Conditional checkpoint write loses safely after stop, replacement engine, phone change, or owner change; delete drains inserts.
15. Live/history collision leaves richer live row durable before UI/webhook emission.
16. DB-only chat list works without engine and includes chats absent from live list.
17. `@c.us`, `@s.whatsapp.net`, and mapped `@lid` collapse into one chat/thread offline.
18. Cursor pagination has no gaps/duplicates under concurrent inserts and equal timestamps.
19. PASS/FAIL/INCONCLUSIVE legacy audit and sync-error clearing rules persist correctly across restart.
20. Existing dedupe, logout teardown, reconnect fences, and live message behavior regressions remain green.

Then run OpenWA focused suites and production builds. No real production number is disconnected or re-linked for verification.

## Deployment and rollback

1. Extend constrained `ops/wa.sh` with fixed OpenWA backup and image-provenance commands; do not expose arbitrary remote shell.
2. Record running container image ID/digest, compose state, health, and source checksums.
3. Run sanitized legacy identity audit. Any conflict stops deployment for operator decision.
4. During deployment stop window, create timestamped archive of entire `openwa-data` volume (SQLite databases plus credentials), verify checksum, and verify expected database/session entries exist without printing secrets.
5. Deploy reviewed OpenWA API/dashboard artifacts. Automatic additive migration runs only after verified backup.
6. Verify container uses newly built image ID, health, authenticated gate, migration ledger/schema, sanitized import state, DB duplicate count, and selected source/build checksums.
7. Perform non-destructive browser checks for stored chat list/thread and pagination.

Old image must never boot against post-migration live volume: even with auto-start disabled it rewrites protected `ACTION_REQUIRED` state. Emergency choices are roll-forward, or - after separate destructive approval - stop service and restore matched pre-deploy database/credentials plus old image together. Restore loses post-deploy data, so no automatic rollback occurs.

## Out of scope

- Allowing multiple WhatsApp numbers inside one session.
- Deleting or rewriting old-number history to permit session reuse.
- Guaranteeing messages WhatsApp itself no longer exposes to linked-device history APIs.
- Changing Bitrix iframe ownership, Django authentication, CRM sync, or n8n behavior.
- Performing a live unlink/relink test against the currently connected production number.
- Claiming exact date-window history guarantees for Baileys.
