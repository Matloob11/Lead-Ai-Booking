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
- **Root cause:** each inbound message is its own `assistant_turn`; while turn A thinks, message B arrives and gets
  turn B. `_newer_inbound` makes A skip *only if B is already stored when A checks*; when B lands during A's model
  call both reply (50390's 13:38 turn shows "skipped: a newer message arrived while thinking" worked once, then
  not). The slot line is code's (`shops.slot_offer` via `residential` invitation), re-added on every turn whose
  reply "has no slots", so each duplicate turn re-offers.
- **Should have:** one reply per burst; never repeat a line sent in the last few minutes.
- **Fix:** code: (a) a per-conversation lock around `_run_claimed` (Redis `SET NX`, 60 s) so one turn runs at a
  time and the second re-reads the burst; (b) in `engine.settle`, drop any sentence equal to one of our last three
  outbound bodies (`transcript` has them) unless the customer asked for it again; (c) `slot_offer` not re-added
  when the same pair went out in the last 30 min and the customer has not answered it.
- **Test:** two inbound rows 2 s apart → one reply; a reply equal to the previous one is dropped.

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
- **Fix:** code: the charge paragraph only when a charge word was asked (deposit, Ejari, DEWA, chiller, cheques,
  fees), never on "how much" (that is the band); `clean_reply` cuts at the last sentence end before 600.
- **Test:** "how much?" → band only; a 700-char reply → ends at a full stop.

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

## Order of work
1. I01 (concurrency + late answers + sweep), I03, I04, I06 — the four that lose customers. Ship together through
   the gate with round 8 (`leadai-2e` 315c39b).
2. I02, I05, I07, I09, I13, I14.
3. I08, I10, I11, I12, I15 (process).
