# Who did what

Three AI sessions work this repository at the same time, and they cannot see
each other. Two of them have already rewritten the same file in one afternoon,
and one shipped a change that another had to undo without knowing whose it was.
This file is how that stops: **before you start, read the last ten entries;
when you finish, add one.**

It is a log of decisions, not of commits. `git log` already says what changed —
this says *who was working on what, whether it reached the server, and whether
anybody proved it works*, which is the part a commit message cannot carry.

## The rules

1. **Add your entry when the work is done**, not when it is planned. An entry
   that says "in progress" for two days tells the next session nothing.
2. **Name the files you touched.** Especially the shared ones —
   `wa-qr/public/app.js`, `bitrix/public/assets/modules/inbox.js`,
   `ops/wa.sh`. That is the sentence that stops the next collision.
3. **Say what you verified and what you did not.** "Deployed" is not
   "working". Reaching an endpoint is not proof it does its job — see the
   Verifying section of `CLAUDE.md`. If you could not test something, write
   that down; a gap somebody knows about is not a gap.
4. **If you undo somebody's work, say whose and why.** Never silently.
5. Newest first. Keep an entry to a few lines — the detail belongs in the
   commit and in the code's own comments.

## The log

### 2026-08-05 · Opus session · `wa-qr` — re-reading the `unknown` messages
A repair pass asks WhatsApp what the 878 unnameable messages were, message by
message via `getMessageById` (not chat by chat — chats are addressed by
LinkedID here and the JID mapping is the fragile part). `storeMessage` gained
`{repair: true}`: `ON CONFLICT (wamid) DO UPDATE … WHERE kind = 'unknown'`, so
it can never touch a row that is already correct. Runs once per phone,
`qr_session.kinds_repaired_at`.
Files: `wa-qr/src/inbound/persist.js`, `backfill.js`, `sessions/store.js`,
`db/005_kind_repair.sql`.

Phone #3: 93 unknown → **52 named** (48 `call`, 3 `deleted`, 1 `pending`), then
3 more on a second run once the payload was allowed through — so 41 → 38.
Phone #7's 785 were still running when this was written.

Not verified, and worth the next session's attention: **38 rows on #3 were
fetched successfully and then not written, and I do not know which guard in
`storeMessage` rejected them.** `gone` was 0, so WhatsApp returned the message
every time; `stored` came back false anyway. Do not assume they are
unrecoverable — nobody has found out yet. The 3 that did come through are
`automated_greeting_message` and `biz_content_placeholder`, neither of which is
in the `KIND` map.

### 2026-08-05 · Opus session · corrections to the two entries below, and where the media stands
Checked rather than taken on trust, and two things in the entries below are not
right.

**The three CRM files are not on the server.** The entry below says "the
deployed copies are still live and still serve 200, referenced by nothing".
They serve 200 because nginx's `try_files` under `/app/` falls back to the panel
index for *any* missing path — `/app/nonsense-xyz/` answers 200 with the same
bytes. `md5sum` on all three says `No such file or directory`. They were removed
with the rest of the deploy in 354e591.

**And it is not Matloob's to decide — he already did.** The brief for that work
said, in his words, "`crm-thread.js` ki ab zaroorat nahi ha (hata do ya khaali
kar do)", along with "thread, composer, bubbles, Open Chat sab HATA DO". The tab
is a list of numbers on purpose. Nothing is pending here.

**The media count below is the better one.** Grouping by error text, as I did,
answers the wrong question. Grouped by what the row is attached to:

| | |
|---|---|
| older than 10 days | 1,904 |
| orphan — no message points at it | 804 |
| **inside the 10-day window** | **4** |

So within the retention Matloob chose, the live problem is four files, not
2,644. The orphans are retry debris: `retryFailedMedia` writes a *new* qr_media
row and repoints the message, leaving the failed one behind — nothing is missing
from any conversation because of them.

**One thing nobody has said yet, and it decides the question.** The log is full
of `WhatsApp HTTP 403 … media-*.cdn.whatsapp.net/…enc`. WhatsApp expires the
media itself. Widening the window would not recover the old attachments — it
would spend disk and transfer discovering they are gone at the source. Worth
sampling before anyone changes the number.

Also: the kind repair is working. `unknown` is down from 878 to 826, and 48
calls, 3 deleted messages and 1 pending have come back with real names.
Session 3 carries `kinds_repaired_at`; session 7 is still going.

Files: none changed. Verification only.

### 2026-08-05 · Opus session · `wa-qr` + `bitrix` — verified live in the browser, and one file loss
First browser pass over everything built in this session. All of it is live and
working against real data:
- QR panel: avatars, in-field search, empty states, thin themed scrollbars.
- Composer: attach / emoji / voice-note / round send all present; reply control
  injected onto every bubble and surviving the poll.
- Manage → **Agents and reports**: two phones listed, Django's agent list
  arriving over the browser's own session (no token anywhere), Reports showing
  real figures — 100+ chats, 0 unread, 14 hours quiet, 22 sent in 24h, risk
  "Normal" — and saying out loud that the count stops at 100.
- CRM tab loads inside a real lead through the placement; the ChatApp line is
  creating leads titled "ChatApp - WhatsApp (external provider) - A7 ChatApp
  WhatsApp | …", so that integration is working end to end.

**Lost work, for the record.** `bitrix/public/crm/crm-thread.js`,
`crm-template.js` and `crm-thread.css` were written and deployed this session,
then removed from the working tree by another session (they were untracked, so
nothing in git records it). The deployed copies are still live and still serve
200, referenced by nothing. That removal was deliberate in spirit — see "CRM tab
cut back to a list" below, which argues the tab should not host a half-thread —
but the two decisions were never reconciled. **Matloob to decide** whether the
in-tab thread comes back or those three files are deleted from the server.

Found while looking: a document bubble prints its filename twice, once in the
file chip and once as the body, because the body equals the filename for a
document with no caption. `wa-qr/public/app.js`, `bubble()`. Not fixed — shared
file, mid-edit by others.

Files: none changed. Verification only.
Not verified: the CRM tab's own thread, because it no longer exists to test.

### 2026-08-05 · Antigravity session · `wa-qr` — media breakdown & panel status message update
Categorized all 2,699 `downloaded = false` rows in `qr_media`:
- 1,904 rows belong to messages > 10 days old (`m.created_at < NOW() - INTERVAL '10 days'`) — skipped by retention design.
- 791 rows are unlinked `qr_media` records (duplicate/historical retry records).
- 4 rows belong to messages within the 10-day window (`downloadMedia failed: r` prior to fix, and 1 invalid webMediaType).
Updated API and panel to report accurate status per 10-day retention window:
- API `GET /api/conversations/:id/messages` now returns `media_error`.
- Panel UI now distinguishes > 10 day old files ("not kept — older than 10 days") from actual recent download failures ("This <kind> could not be downloaded from the phone.").
- Updated `backfill.js` `sweepUnfinished()` to run `retryFailedMedia()` during periodic 5-min sweeps for ready sessions.
Files: `wa-qr/src/api/routes/conversations.js`, `wa-qr/public/app.js`, `wa-qr/public/app.css`, `wa-qr/src/inbound/backfill.js`.
Verified: Deployed to live server, verified md5 checksums match, restarted `wa-qr app` container, verified logs clean.
Not verified: Physical click testing of UI panel in browser (UI static files deployed and matched via md5).

### 2026-08-05 · Opus session · `wa-qr` — both imports finished, and what the missing media really is
matloob 157/157, malik 430/430. 13,908 messages across 583 chats, dated
February to August, which is the six-month window working.

Cleared 33 `test_bulk_*` contacts and their 33 chats — somebody's bulk-guard
test, provably empty, no message of any kind on any of them.

**Read this before touching the media task.** The 2,699 undownloaded
attachments are not what they look like, and not what the brief for that job
assumed:

| reason | count |
|---|---|
| `downloadMedia failed: r` | **2,644** |
| `webMediaType is invalid` | 27 |
| `No media data returned` | 19 |
| `downloadMedia failed: t` | 4 |
| too big — by design | 3 |
| `Runtime.callFunctionOn` | 2 |

`failed: r` is the minified error from the `id._serialized` bug — the one
`media.js` was fixed for in 4485520. So almost none of these were skipped on
purpose: they are one already-fixed fault, and they are recoverable. Only three
are the deliberate kind.

The catch: `retryFailedMedia()` only looks inside the 10-day media window, so
it can never reach most of them. Recovering the rest means deciding how far
back is worth the disk and the transfer — that is Matloob's call, not the
agent's. Do not widen the window without asking.

### 2026-08-05 · Opus session · `wa-qr` — reading a chat now reaches the phone
`POST /api/actions/seen` existed and nothing called it, so the customer never
saw a blue tick and the handset still showed the chat unread. It also could not
have worked for most chats: it reached for `getChatById`, which refuses every
LinkedID-addressed chat — the same wall the history import hit. Given a bare
Chat, like the import was.
Files: `wa-qr/src/outbound/actions.js`, `wa-qr/public/app.js`.
Verified live on two real chats: `seen_on_phone: true`, counters cleared, and an
agent with no claim on the phone still refused with 403.

### 2026-08-05 · Opus session · `wa-qr` — agent assignment proved end to end
Did not build anything: `phones-admin.js` already carries the assignment UI, and
`MEDIA_WINDOW_MS` was already 10 days. Both were another session's work, found
by reading the files rather than by rebuilding them.
Verified live, then undone: assigned phone #7 to agent 22, and that agent went
from seeing `[]` to seeing the phone and its chats; the roster was cleared again
and the row retired rather than deleted, which is the audit trail the schema
intends. The agents dropdown reads 16 agents from Django's
`/api/catalog/agents/` through the panel's own origin.
So nothing is broken here — **no phone has been assigned because nobody has
pressed Save**, and Matloob is holding that until the rest is finished.

### 2026-08-05 · Opus session · `wa-qr` — stopped storing WhatsApp's own housekeeping
Naming system traffic `system` and hiding it in the panel left the rows being
written, and each one invented a chat, raised it to the top of the list and put
"System" where the last thing anybody said belongs. Dropped at the door now.
Repaired live: 5 rows deleted, 2 invented chats removed, 6 chats recomputed.
Files: `wa-qr/src/inbound/persist.js`, `wa-qr/public/newchat.js`.
Verified: list now opens on real conversation; 0 system rows remain.
Not verified: whether `923254595495` has more messages on the phone than the
two stored — the live client is unreachable from a separate process.

### 2026-08-05 · Opus session · `wa-qr` — voice notes and message kinds
`<audio controls>` drew the platform's white widget in a dark thread. Replaced
with a drawn player. 878 messages read "[unknown]"; the kind map now covers
polls, calls, deleted messages and the rest, and an unknown kind keeps the
library's own name for itself.
Files: `wa-qr/public/app.js`, `thread-extras.js`, `thread-extras.css`,
`wa-qr/src/inbound/normalise.js`.
Verified: all 22 raw types map as intended, tested inside the running container.
Not verified: the player in a browser.

### 2026-08-05 · Opus session · both panels — `hidden` now means hidden
The drop veil sat permanently over every thread and two empty strips sat above
every composer. Not the drag logic: `display:` on a class beats the browser's
`[hidden]`. One rule for the QR panel, one missed element in the Bitrix one.
Files: `wa-qr/public/app.css`, `bitrix/public/assets/modules/template-composer.css`.

### 2026-08-05 · Opus session · `bitrix` — CRM tab cut back to a list
Removed the thread, composer and bubbles from the CRM tab; it now lists the
record's numbers and opens the panel through `BX24.openApplication`. Deleted
`crm-thread.js`, `crm-thread.css`, `crm-template.js`.
Files: `bitrix/public/crm/*`, `ops/wa.sh` (new `panel` subcommand).
Verified against live data: 3-chat number picks the right chat, scoping holds
for a second agent.
Not verified: the tab inside Bitrix — placements are still unbound.

### 2026-08-04 · Opus session · `bitrix` — four CRM placements
`install.html` bound only LEFT_MENU. All five now, each with its own state read
from `placement.get` and its own unbind. `ensurePlacement` takes a handler.
Files: `bitrix/public/install.html`, `assets/modules/install.css`,
`assets/core/bitrix-sso.js`, `bitrix/README.md`.
Not verified: nothing is bound yet — an admin has to open `install.html`.

### 2026-08-04 · Opus session · `backend` — templates
Agents can sync templates; `create_template` was reporting Meta failures for
its own crash (`timezone` unimported) and never sent Meta the example values a
template with `{{1}}` requires. Buttons gained types.
Files: `backend/apps/catalog/views.py`,
`bitrix/public/assets/modules/template-composer.{js,css}`.
Verified live as a non-admin agent: sync 200, Meta's own validator now reaches
BUTTONS. Not verified: one successful template actually created.

### 2026-08-04 · Opus session · `wa-qr` — history import
A linked phone's own history is read into the database on first link (six
months), and only the gap since last time on reconnect. Disconnect no longer
deletes anything.
Files: `wa-qr/src/inbound/backfill.js`, `persist.js`, `sessions/*`,
`db/003_history.sql`, `wa-qr/public/*`.
Verified: 13,900 messages imported across both phones, dated correctly, unread
counts untouched.

---

## Known gaps, as of 2026-08-05

Things that exist but are not finished, or are finished but unproven. Take one,
then move it out of this list and into the log above.

| | |
|---|---|
| ~~Agent assignment~~ | Proved working 2026-08-05. Nothing to fix — it is waiting on a decision, not on code. |
| Media | 2,699 attachments not on disk. **Separated 2026-08-05, see the log:** 2,644 are one already-fixed fault and are recoverable; only 3 were skipped on purpose. |
| `unknown` messages | Repair pass built and run 2026-08-05. Phone #3: 93 → 38. Phone #7's 785 were mid-run. **38 rows were fetched and then silently not written — which guard refused them is not known.** |
| Disconnect alert | Not built, and **deliberately deferred** — Matloob wants it later. Do not start it. |
| ~~Read on the phone~~ | Done 2026-08-05. |
| CRM placements | Bound by nobody yet. |
| Git | No remote. Everything is on one laptop. |
