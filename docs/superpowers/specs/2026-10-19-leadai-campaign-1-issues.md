# Lead AI: the first mixed campaign (2026-10-19), every issue and its fix

Campaign `intl_city_property_reconnect` (campaigns 549–553), sent 12:18 Dubai from 971581058719–723 to 1,295
leads. 222 customers replied; 130 chats got the bot's answers (714 messages: 76% right, 15% small slips, 9% wrong;
by chat: 54 good, 36 minor, 34 bad, 6 stuck); 92 got nothing until `leadai-answer-late` answered 86 of them at
15:20–15:33 (the other 6 were the customer's own auto-reply).

The reviewed transcripts, with the engine's own turn records, are in the session scratchpad
(`campaign_review/transcripts.txt`, `issues_all.txt`); chat ids below are `inbox_conversation.id`. Every root cause
here was read off the live code (branch `leadai-2e`, live round 6 = `9693e78`), not guessed.

Owner key: **code** = a guard or flow in `apps/leadai`; **prompt** = `assistant/prompt.py`; **ops** = compose,
settings or process. Severity: how many customers it hurt and how badly.

## A. The queue (92 customers, the worst)

### I01 — 92 replies dropped as "too old" (high, ops + code)
- **What the AI did:** nothing. 39 tapped "Yes, still looking", 12 tapped and typed, 25 typed ("Can I see the
  studio"), 16 tapped "Not now"; none got a reply. 243 "stale" alerts went to the agents instead.
- **Root cause:** `deploy/docker-compose.yml` runs `worker-leadai` with `--concurrency 2`. A turn with a model call
  takes 8–30 s, so 222 near-simultaneous replies are ~20–30 min of work. `engine.run_turn` skips any message older
  than `STALE_AFTER = 15 min` (engine.py ~3432) and raises the stale alert; the beat sweep (`tasks.py` MISSED_FROM/
  MISSED_UNTIL = 2–15 min) requeues only inside the same 15-minute window and only when no later message exists in
  the chat, so a customer who typed twice was never requeued.
- **Should have:** answered within a minute, or at worst late with a short apology.
- **Fix:**
  1. ops: `--concurrency 6` on worker-leadai (the model calls are I/O-bound; the box is idle during them).
  2. code: in `run_turn`, a stale message with no outbound after it is answered, not dropped: keep the alert,
     prefix nothing (the normal reply reads fine late). Keep "too old" only when someone replied since.
  3. code: the sweep requeues the newest answerable message of a chat (by pk, as `_newer_inbound` reads it), not
     only chats with a single message.
  4. process: a campaign of this template at ~100 leads per number per day (board T72/T99), or paced over hours.
- **Test:** a burst of N messages across M chats with a 2-slot worker: every chat answered once; a message with an
  agent reply after it is skipped. `leadai-answer-late` already proves the late path works (86 of 92).

### I02 — the same slot offer four times in ten minutes; two bot messages to one customer line (medium, code)
- **Chats:** 50390 (3:00/5:00 PM offered at 13:40, 13:45, 13:49, 13:50), 50282 (two messages at 13:12, two at
  13:14), 50157.
- **Root cause (corrected after reading `filters.drop_repeats`):** a text-repeat guard already exists and is
  right: it keeps questions and code's fixed lines on purpose ("a repeat beats no answer"), and the slot offer is
  both. The four copies in 50390 were four *separate turns* at 13:40, 13:45, 13:49, 13:50, one per customer
  message, each legitimately closing with the slot line. The real defect is cadence: each inbound message gets its
  own `assistant_turn`; `_newer_inbound` skips turn A only if B is stored before A's check, so two turns overlap on a
  burst (50282: two bot messages at 13:12 and again at 13:14). An extra text filter breaks 10 existing tests and
  is the wrong layer (tried and reverted, round 10 branch).
- **Should have:** one reply per burst; a slot pair re-offered only once an answer to it is due.
- **Fix:** code: (a) a per-conversation lock around `_run_claimed` (Redis `SET NX`, TTL = TURN_BUDGET) so the
  second turn waits, then re-reads the burst and skips if the first answered it; (b) `slot_offer` not re-added when
  the same pair went out in the last 30 min and the customer's words answered nothing about it (`offers.count_invitation`
  already counts invitations: use it).
- **Test:** two inbound rows 2 s apart → one reply; the same pair not twice within 30 min without an answer.

## B. Stop, Not now, lost leads

### I03 — "Not now" + "Stop messages" answered with a price pitch (high, code)
- **Chats:** 50108 and 9 similar ("already found", "got the flat", "too late" also pitched).
- **Root cause (50108, read from the rows):** the two taps arrived out of order: `Not now` is pk 202487 at
  13:08:07, `Stop messages` is pk 202486 at 13:08:08 (the gateway delivered them swapped). `_burst_opt_out` reads
  the *last* item of the burst by pk → "Not now" (a shops-template "Not now" is `not_now`, no stop), so the STOP
  tap before it was ignored, and the model then answered "Not now" with the studio price. A second cause for the
  typed cases: `rules.PHRASES` has no "already found a flat / got the flat / too late / deal is closed", so
  `opt_out_from_text` returns None and the model sells.
- **Should have:** a Stop anywhere in the burst wins: one confirmation, then silence. "Already found" = lost
  (polite close, no pitch).
- **Fix:** code: `_burst_opt_out` scans the whole burst and takes the strongest opt-out (STOP_ALL > wrong number >
  not interested > not now), not the last item; add the lost phrases to `rules.PHRASES` (lost, not stop); add
  "welcome" to `ACKS`; "maybe next July / next year" → a follow-up date in state, not Lost.
- **Test:** burst [Stop messages, Not now] in either order → `stop_all`, one line, no model call.

## C. Hand-overs and calls

### I04 — "Urgent for call" got a price pitch, no hand-over, no alert (high, code)
- **Chats:** 50005, and 11 more where the bot *promised* an agent would call/contact but handed over nothing.
- **Root cause:** `people.asks_for_call` needs "call me/us/back", "arrange a call", or a request verb; "Urgent ‼️
  for call 📲" matches none (`_CALL_REQUEST` has no bare "for call"/"call please"). The model also tagged no
  handover, so `settle_handover` saw nothing. Separately, when the model writes "our agent will contact you soon"
  (50020) without a handover tag, `people.says_colleague_replies` keeps the sentence but nobody is alerted.
- **Should have:** a call request → `call_requested` handover + alert + the call-slot line; any reply that promises
  a person's call/contact must carry a handover.
- **Fix:** code: widen `_CALL_REQUEST` with "for (a) call", "call please", "need (a) call", "call karo/karein",
  "اتصل بي"; in `engine.settle_handover`, if `people.promises_call(reply)` or `hands_over(sentence)` is true and
  `handover.needed` is false → set `customer_asked_human`/`call_requested` and raise the alert (do not just cut
  the sentence). Media-only bursts (video, sticker, document with no text) → `media_received` handover.
- **Test:** the 50005 reply through `run_eval` with the real words → handover + CALL_SLOTS; "Our agent will contact
  you soon" with no tag → handover true.

### I05 — a call request held 20 minutes by the reply cap (medium, code)
- **Root cause:** `caps.py` holds the Nth reply in a window regardless of content.
- **Fix:** code: `caps.is_capped` returns False when `people.asks_for_call` or an opt-out is in the burst.

## D. Bookings and slots

### I06 — "tentatively held 4:00 PM" with nothing saved; full name never asked (high, code)
- **Chats:** 49569 ("Okey" → "held 4:00 PM", no appointment row), 49844 (7 PM accepted, no name, no
  confirmation), 50157.
- **Root cause:** the model writes "I have tentatively held…" on a bare "Okey"; `residential.settle` books only on
  a time the customer named (`upgrade_exact_time`/`own_time`), so no row is created, but `claims_done` (guard 7)
  lets "tentatively held" through because it is not in `_CLAIM` ("booked|confirmed|reserved|scheduled"); the
  full-name gate (`full_name_gate`) runs only on a stored tentative, which never existed.
- **Should have:** "Okey" to two slots → ask which slot (or take the first only if the customer said so), then ask
  the full name, then confirm day/time/office.
- **Fix:** code: add "held|holding|hold the .* slot|kept .* for you" to `_CLAIM`; when the customer's bare yes
  follows a two-slot offer, code asks "3:00 PM or 5:00 PM?" (one line, `residential.line("res_which_slot")`); the
  name gate also fires on a reply that claims a hold.
- **Test:** 49569's reply on "Okey" → the claim cut, the which-slot line; then "4 pm" → tentative + name ask.

### I07 — two different slot pairs in one message; four slots; today's slots after "not today" (medium, code)
- **Chats:** 49818 ("3:00 or 4:00 … 3:00 or 5:00"), 50157 (Monday/Tuesday + today), 50282 ("Not possible today"
  → still today's 4:30/5:30), 50093 ("Not today").
- **Root cause:** `filters.offer_slots` appends code's slot line when it finds no *valid* slot sentence, but the
  model's own slot sentence survives when it names past-but-plausible times; "not today/not possible today" is not
  read by `shops.invitation_slots`, which keeps `now`-based slots.
- **Fix:** code: when code adds its slot line, drop every model sentence that `filters.offers_time`; "not today",
  "aaj nahi", "tomorrow/kal" → `invitation_slots` starts from the next open day; cap one pair per message.
- **Test:** 49818's reply → exactly one pair; "Not possible today" → both slots on a later day.

### I08 — confirmation text sent, map pin after; "location above" with none sent (low, code)
- **Fix:** send the location pin before the sentence that references it, or drop "the location above" when no pin
  went this turn (`residential.settle`, `address_sent`).

## E. Answers and content

### I09 — questions dodged: parking, family building, "any units in England?", "studio and 1BHK both" (medium, prompt + code)
- **Chats:** 50026, 50093, 49654, 50244, 50390 ("agency charges" / "ranges from?").
- **Root cause:** prompt: RES_SYSTEM tells the model to move the flow forward but not to answer the exact question
  first; code: `residential.settle` cuts "Our agent will confirm the details" into generic lines and `charges_asked`
  does not read "agency charges", "brokerage", "ranges from", so the commission line never goes.
- **Fix:** prompt: "Answer their exact question in one line first, even if the answer is 'it depends on the
  building; the agent confirms at the viewing', then continue." code: add "agency charges|brokerage|agent fee|ranges
  from" to `_CHARGE_ASKED["commission"]`; "parking|family building|bachelor" get a one-line code answer ("Parking
  and the building's rules depend on the building; our agent confirms them at the viewing.") when the model's
  reply ignores them; "studio and 1BHK" → `band_answer` for both units.
- **Test:** each real customer line with the real reply → the answer sentence present.

### I10 — deposit/Ejari/DEWA/cheques paragraph nobody asked for; a message cut mid-word (low, code)
- **Chats:** 49804, 49818, 50051, 50054, 50282 ("…passp" cut).
- **Root cause:** `charges_asked` returns a set for a price question too (`_CHARGES_IN_GENERAL` matches "how
  much"), so every charge line goes; `filters.clean_reply` ends with `text[:REPLY_MAX]` (600) — a hard cut.
- **Fix:** code: `clean_reply` cuts at the last sentence end before 600 (done, round 11). The charge paragraph unasked:
  an `unasked_charge` cut on an empty set was tried and reverted — rounds 1 and 2 of the gate settled that an empty set
  cuts nothing (the paragraph is tolerated); a reply it pushes over the limit keeps code's own line through
  `residential._fit` (round 11, the slot pair too). The paragraph itself stays a prompt matter.
- **Test:** a 700-char reply → ends at a full stop (done); "how much?" → band only (open).

### I11 — mixed language: code's Roman-Urdu slot line inside an English reply (low, code)
- **Chat:** 50157 (`language` = ur_latin from one Urdu word; the model wrote English).
- **Fix:** code: code's own lines follow `rules.guess_language(reply)` when it is confident, else the chat's
  language; never mix in one message.

### I12 — "Perfect, the Spain Cluster studio" when the customer asked "any studio available?" (low, prompt)
- The cluster came from the old lead, not from the customer. Prompt: confirm a lead-sourced cluster as a question
  ("You asked about Spain Cluster earlier — still that one?"), not as a statement.

## F. Tracks and claims

### I13 — a buyer got the yearly rent; an owner was invited as a tenant; CBD read as "another area" (medium, code)
- **Chats:** 49732 (buy → rent band), 50020 ("I am owner, I want to rent it" → photos + viewing), 49953 ("units in
  cbd" → other-area line), 50169 ("family space" → switched to other).
- **Root cause:** `tracks.decide` takes the deal from the model's `wants_buy` tag or facts.intent; here the model
  kept `intent: rent` and the words "I would like to buy" are not read by code (no `_BUY_WISH`, unlike
  `wants_rent`). Owner: `facts.intent = rent_out` is recorded but nothing in `residential.settle` hands an owner
  over, so the rent flow continues (photos, slots). CBD: the live cluster list is Spain, France, England, China,
  Persia, Morocco, Emirates, Greece, Russia, Italy — no CBD — so "cbd" hits the model's `other_area` tag. "Family
  space": the model tagged `other_need`, and `_from_tag` switches a stored rent track to OTHER on that tag alone.
- **Fix:** code: `tracks.wants_buy(words)` ("buy|purchase|kharidna|أشتري" with a home noun) switches to SALE;
  `intent == rent_out` or "I am (the) owner|landlord|my studio/flat" → handover `owner` with the owners line, no
  photos, no slots; add "CBD" (Central Business District, a cluster of International City) to the cluster list and
  `_CLUSTER_WORDS`; a stored rent/sale track never switches to OTHER on `other_need` alone when the words name no
  other property (keep the home; answer the need: "family" → suggest the one-bedroom band).
- **Test:** each real line → the right track and reply.

### I14 — availability claims that went out (medium, code)
- **Chats:** 49958 ("Type 3 large shops are available in all clusters"), 50020 ("see the exact available
  option"), the shop card "We have 3 types available", the confirmation's "take you to the available apartments".
- **Root cause:** `claims_availability` runs only on the residential path (`residential.settle`); the shops path
  has no availability guard, and two of the sentences are *code's own lines* (shops type card, the rent
  confirmation).
- **Fix:** code: reword the two code lines ("Shops come in three sizes"; "…and take you to see apartments of that
  type"); run `availability_talk` on the shops path too; keep the question allowance.

## G. Alerts and the desk (process)

### I15 — hand-over alerts answered 40–80 minutes later, or not at all (process)
- 42 `handover_waiting` escalations. Nobody held Lead AI access until 2026-10-19 15:52 (now Hina Sultan,
  Mohammad Farhan, Shoaib Malik). Agree who watches the desk during a campaign and the target (under 10 minutes).

## Not bugs (reviewers flagged, code is right)
- "Stop" alone → one confirmation, then silence: correct in every chat.
- Rent quoted yearly, no phone number ever given, no colleague named, brokers paused: correct.
- Photo captions "same type": correct (Q36).

## Order of work and status (updated 2026-10-19 18:27 UTC)
1. **Round 9's gate (3e45c79): failed on one money scenario** (shops-res-monthly-figure, 1 of 2 runs: the model gave
   no band on "how much per month?"); 99.0% overall, 187 of 188 shop scenarios. Nothing deployed; live stays round 6.
   Its fixes (I01, I03, I04, I06) are carried forward.
2. **Round 10 on `leadai-2e`, in the gate now:** round 9's fixes + the monthly band + I05 (call requests bypass the
   cap, proven live) + I07 (one pair of slots: the model's own goes when code's closes the message) + I13 (owner words;
   a stored home track over a bare other tag, CBD included; `wants_buy`: rent → sale on a wish to buy). 2031 tests OK.
3. **Reverted after trial:** an I02 text-repeat guard in `engine.settle` (10 tests: `filters.drop_repeats` keeps
   questions and fixed lines on purpose) and a wider cut inside `filters.offer_slots` (10 slot rules). Both root
   causes re-stated above.
4. **I09 done on `leadai-2e` (after round 10's commit; ships in round 11):** "agency charges" is a commission ask;
   "ranges from / roughly" after our commission line gets the figure; an answer to the customer's own family-or-
   bachelors question is no longer cut as screening (it was, three times in chat 50093: a code bug, not a model slip).
   Parking: the model answers when it chooses to (chat 50244) and the prompt already says "answer their question
   first" — no guard.
5. **I14 done on `leadai-2e` (after round 10's commit; ships in round 11):** a stock claim on the shops track is cut
   (`claims.claims_stock`, with a shop noun, so the residential guard's reach is unchanged); the shop-types card says
   "Shops come in 3 types" instead of "We have 3 types available". The rent confirmation's "take you to the available
   apartments" stays on purpose: it is the policy check's own approved phrase and nine fixtures pin it.
6. **Round 10's gate (context 318b295): failed on three scenarios, one run each** — declines (the ten-word "No thank
   you, I already rented a shop last month" is past `opt_out_from_text`'s whole-message limit, and the model tagged it
   unclear), shops-res-invitation-two-slots (a 698-character reply: `clean_reply`'s 600 cut took code's two slots, last
   in the message), shops-res-cluster-unknown (the same reply passes its round-2 fixture: variance, no gap found).
   99.1% overall, 187 of 188 shop scenarios. Absorbed in c719291: `rules.declines` is read after the model in
   `engine.settle` (never code-first, so a shops chat still asks about a second shop first, T27); the slot block fits
   the reply with code's pair kept (`residential._fit`); `clean_reply` cuts at a sentence end (I10's second half).
   2056 tests OK.
7. **Round 11's gate (context c719291): failed on one strict scenario, one run** — shops-gate-half-hour #1: "viewings
   start on the hour. I can hold a slot for you at 4:00 PM or 6:00 PM" and a tentative with no hour; code cut the hourly
   sentence, but `passed_over_hour` read the offer's shape alone, and one slot beside theirs plus one an hour and a half
   off is no passing-over by round 1's rule. 99.3% overall, 186 of 188 shop scenarios; the other three failing runs were
   the model's own (shop-invite, shops-same-day-window-96, lang-inshallah-english), each passing its other run. Absorbed
   in b71a30a: the reply's own hourly sentence makes their off-the-hour time the visit's (`claims.says_hourly`, read
   before the cut). 2060 tests OK. Nothing went live; the build context and images hold round 11 (`up` never ran).
8. **Round 12 is live (2026-10-19 18:50 UTC, main `94d21f7`):** round 11 + item 7. The gate: 569 of 574 (99.1%), the
   model's own words 299 of 304 (98.4%), every strict scenario every run; Postgres tests on the image leadai 1920, crmlink
   118, inbox 13; `probe-leadai-turn` 19 of 19; no migration. `worker-leadai` runs with concurrency 6 (compose).
9. **Next:** I02 (per-chat turn lock), CBD as a cluster name in the settings list.
10. Then I08, I10's first half, I11, I12; I15 is process (agents watch the desk).
11. Seen in round 11, not strict, no code yet: shops-same-day-window-96 #1 — the model proposed no appointment at all for
    "barah saadhay barah baje ja ke check kar loon ga" (its reply asked the business), so T18 had no tentative to upgrade;
    code books only what the model proposes. A rule for "their own day and hour said plainly, the model proposing nothing"
    would be a new step, not a guard — weigh it against chats where that silence was right.
12. Seen in round 12, not strict, no code: shops-old-lead failed both runs because the model quoted the old lead's CRM
    budget ("around AED 40,000 a year"); `lead_history.drop_quoted` cut it both times, so the customer saw no CRM figure
    (the eval counts the quote itself). shops-sale-price-and-book #2 said "AED 310,000 to AED 350,000 depending on the
    cluster" — the Morocco floor and the general band's top, both from the facts; `sales` reads 310,000 as a band figure,
    the eval wants 330,000. Neither is a code gap; both are the model's own words.
