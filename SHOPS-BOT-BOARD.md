# International City Shops bot — task board

Source: "International City Shops – WhatsApp AI Chatbot Build Pack" (Malik, 2026-10-12).
Order: **Bot 2 first** (old shop leads, campaign-first), **Bot 1 later** (portal inquiries, client-first).
Built inside the existing Lead AI assistant (`backend/apps/leadai/`, panel `bitrix/public/assets/modules/lead-ai/`), not in n8n.

The path Matloob chose: the Bitrix CRM "WhatsApp campaign" popup with the **Lead AI** box ticked sends the template; every reply lands on the Lead AI screen; the assistant talks there and books the office viewing.

---

## How Claude and Cursor share this board

1. **Claim before you start.** Put your name and the date in *Owner* and set *Status* to `Doing`. Check `git status` / `git log` on the files first (CLAUDE.md).
2. **One task, one owner.** If you need a file on the other side's list, add a line under *Requests* at the bottom instead of editing it.
3. **Done means live and proven.** Deployed the CLAUDE.md way and checked on the server. Then set `Done (date)` with a one-line proof, and add a TASKS.md entry.
4. **Commit only your own paths.** Use `git add <paths>`, never `git add -A`, because the tree holds other sessions' work. Push to `origin` (github.com/Matloob11/Lead-Ai-Booking).
5. **Never commit:**
   - `ops/bitrix-aws/*.config.php` and `*.env` (live passwords and the HMAC secret)
   - the 3CX tools (their source holds an OpenAI key and webhook tokens)
   - number rosters and PDF/xlsx dumps

   `.gitignore` already blocks all of these.

| Side | Owns |
|---|---|
| Claude | `backend/apps/leadai/**`, `bitrix/public/assets/modules/lead-ai/**`, `leadai_eval.py`, `ops/catalog/probe-leadai-*` |
| Cursor | `ops/bitrix-aws/**` (popups `a7_lead_wa.*` / `a7_renewals_wa.*`, Bitrix fields, forms, robots), `backend/apps/campaigns/crm_leads.py` |
| Shared — announce here first | `backend/apps/{inbox,gateway,crmlink,campaigns}/**`, `backend/a7wa/settings.py`, `ops/wa.sh`, `deploy/docker-compose.yml`, `bitrix/public/index.html` |

Status values: `Open`, `Doing`, `Blocked Qn/Dn` (waiting for a decision or data below), `Done (date)`.

---

## Where we stand (checked 2026-10-13, live server, read-only)

**Bot 2 vs the PDF: 36%.** The PDF has 46 requirements: 0 done, 33 partial, 13 missing. Scoring is done = 1, partial = 0.5. One agent assessed each requirement against code and live data, and a second agent re-checked it.

| Area | Partial / missing | Score |
|---|---|---|
| Sending, templates, list rules | 6 / 2 | 38% |
| Old-lead mode, objections, honesty | 6 / 3 | 33% |
| Shop facts and how the bot talks | 6 / 2 | 38% |
| Qualifying, shop-type list, media, licence | 3 / 4 | 21% |
| Booking to visit | 7 / 2 | 39% |
| Bitrix fields and writes | 5 / 0 | 50% |

**What exists:**
- **Sending:** the campaign popup's Lead AI box puts every chat on the Lead AI screen.
- **The assistant:** gpt-4.1-mini on its own key. It works in bursts behind gates (pause, stop, agent replied, 24 h window, caps).
- **Booking:** office bookings checked against hours (Mon–Sat 10:00–19:30). Code writes the confirmation, in 6 languages.
- **Reminder:** 30 minutes before. Free-form buttons inside the 24 h window, the UTILITY template outside it.
- **Bitrix:** stage 10 + fields + comment on booking. Bell and panel alerts.
- **Opt-out:** STOP / wrong number / auto-reply rules.

**What the PDF needs that the current rules forbid:** these are owner decisions, see Q4.

| Topic | Today (Matloob's 2026-10-09/10 rules) | PDF |
|---|---|---|
| Prices | never stated; code strips AED amounts | quote the type table |
| Documents | never asked | licence copy + "bring licence / EID + cheque book" |
| First question | business activity | "for yourself or for a client?" |
| Invitation | one open question | two concrete slots, never "when are you free?" |
| Persona | no personal name | "Sara" (clashes with Sara = leadbot) |
| Handover / broker | AI keeps running; handover clears after 12 h | bot stops |
| Office | Russia Cluster, Building V02/V03, **Shop 20** | **Office #11**, V03 Russia Cluster |

**Live state:**
- **Switch:** the assistant has been ON for everyone since 2026-10-12 08:25 UTC.
- **Campaigns:** one Lead AI campaign so far (#395 `ic_shops_followup`, from 971581058725 Coastline, 17 leads). It made 16 chats, of which 2 replied: 4 AI replies, 0 bookings.
- **Maps:** there is no Maps link and no pin set.
- **Reminder template:** APPROVED on 62 WABAs, but **missing on the Coastline WABA** the campaign uses.

---

## Decisions (Q)

**Decided** means Matloob said it; **default** means Matloob accepted the recommended answer ("ap baki start karo", 2026-10-13) and may still change it.

| # | Question | Answer |
|---|---|---|
| Q1 | Office address: PDF "Office #11, V03 Russia Cluster" or live "Shop 20, Building V02/V03"? | **open**: Matloob sends it (D2) |
| Q2 | Brand | **decided: AR Properties** |
| Q3 | Bot's name | default: no personal name ("Sara" is leadbot) |
| Q4 | PDF rules (prices, licence copy, yourself-or-client first, two slots, broker stops the bot) | default: **shop campaigns only**; other Lead AI campaigns keep today's rules |
| Q5 | How a campaign is marked "shops" | default: a "Script" choice next to the Lead AI box (C2 + T20a) |
| Q6 | Slots | default: our own booking table, one client per 30-min slot for the whole office |
| Q7 | Sending | **decided (2026-10-14):** Matloob sends every campaign himself from the CRM popup: picks the leads, ticks Lead AI, chooses Script = International City shops and the template. As many a day as he likes. The system never starts a campaign or drips one. **Automatic follow-ups are wanted:** Template B once after 72 h to non-repliers, the 30-day check-back after "Not now" + yes, and the nudges to a silent customer |
| Q8 | Opt-out | default: block the phone on every number and campaign (Sara too); import the 279 past Unsubscribe/Stop |
| Q9 | "Not now" | default: "check back in a month?" → yes: Template B after 30 days; no: lost |
| Q10 | Which Bitrix stage is "lost" | **decided** (2026-10-13): not interested, already rented, or "Not now" then no → **Not Interested (`1`)**; wrong number or spam → **Junk Lead (`JUNK`)**. Neither needs a stage field |
| Q11 | Broker or "I want a person" | **decided**: the chat gets a **Broker** label in the panel so the team can find and manage it; the bot stays silent until an agent presses Resume |
| Q12 | Shop agent | **decided**: Khurram and Admin Abdul Malik are one person, Bitrix user **1** (portal admin; sees every chat, no number of his own). **Booking alerts go to Matloob** (Bitrix 2311, agent 3). No reassignment on booking (user 1 is the "hold" user) |
| Q13 | Agent alerts | **decided**: Bitrix bell + panel, to Matloob (and the chat owner) |
| Q14 | Assistant ON for everyone while P1 is fixed, or test numbers only? | **open** (still ON for everyone) |
| Q15 | Languages | default: English, Arabic, Urdu/Hindi now; Russian later |
| Q16 | Bitrix fields | default: reuse what exists, create only the missing ones (C3) |

## Data (D)

| # | Data | State |
|---|---|---|
| D1 | Shop facts final: type table; are rents per year; Type 3 cheapest 80,000; viewing hours; clusters, cheques, licences | Matloob sends |
| D2 | Office: final address, Google Maps link, pin latitude/longitude | **Maps link and pin set live 2026-10-14**: https://maps.app.goo.gl/u7xzyea9pPLpRxBD8, pin 25.169639, 55.404667 (from the link's own redirect), via NEW `ops/wa.sh set-leadai-office`. The address text is still open (Q1) |
| D3 | Brand + the `{{2}}` name in "this is {{2}} from {{3}}" | **AR Properties**; `{{2}}` typed per campaign: "Malik" or "Matloob" (template sample: Malik) |
| D4 | Sending numbers | **decided**: active 971 numbers, not coexistence, not assigned: 971581058719, -720, -721, -722, -723, -724, -725, -726 (Coastline Properties / Blue Brick). 971507563104 left out: in daily use (1,755 inbound) with no templates. Only -725 has a proven inbound webhook; the other 7 have never received a message, so each gets one test message before use. `ic_shops_followup` is approved on all 8; `a7_leadai_meeting_reminder` on none (T05) |
| D5 | Media: per type 1 MP4 under 16 MB (30–60 s) + up to 6 photos; office-front photo; Type 1 walkthrough for Template A's header | **Received 2026-10-14** in `backend/Types shops/` (kept out of git). Type 1: 4 photos + MP4 4.7 MB. Type 2: 4 photos + MP4 8.9 MB. Type 3: 7 photos + MP4 4.9 MB. Office front: `office_front.jpg` (JPEG, 240 KB), received 2026-10-14. The sign on it reads "A7 Group Real Estate" while the shop campaigns say AR Properties (Q2): Matloob to confirm that is fine. Type 2 is **600-800 sq ft** (Matloob, 2026-10-14; the folder name "700 800" is not the size), as live settings already say |
| D6 | Shop agent | **decided** (Q12) |
| D7 | The leads | **decided**: International City **shop** leads picked in the Bitrix lead list (filter or ticks; the final pick is real IC shop leads only). The "Mudon" link was a mistake |
| D8 | Test phones | Matloob gives them when Claude asks at test time |
| D9 | Match table (size / budget → type) | default: by size range; by budget, under 48k → Type 1, 48k–80k → Type 2, 80k+ → Type 3 |
| D10 | Closed dates (public holidays) | Matloob sends |

---

## Tasks

### P0 — Now

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T01 | Commit all work, connect GitHub `Lead-Ai-Booking` as `origin` | Claude | — | Done (2026-10-13) |
| T02 | Record the 2026-10-12 switch-on, campaign #395 and this check in TASKS.md | Claude | — | Done (2026-10-13) |
| T03 | Md Sumon (conv 35283) said Yes, then "I will message you"; no booking, no alert. An agent writes to him by hand before the window closes at 2026-10-13 11:02 UTC (only a template after that), and `invites` is reset | Matloob | — | Open |
| T04 | Set the assistant to test numbers only, or keep it on | Matloob | Q14 | Open |
| T05 | Get `a7_leadai_meeting_reminder` approved on the 8 sending WABAs (D4); the submit command takes only numbers with an agent, so it also takes the sending numbers | Claude | — | Done (2026-10-13) — submitted to 43 WABAs, all 8 sending numbers included, PENDING at Meta. 4 refused: 971556829046 (restricted), 971507563104 and 971527514497 ("Invalid WhatsApp configuration"), 447723356623 (HTTP 500) |
| T06 | Paste the Maps link and coordinates in Lead AI → AI settings | Claude | — | Done (2026-10-14) — `has_pin` true live; confirmations carry the link and a pin goes after a booking |
| T07 | One test message from a phone to each of 971581058719, -720, -721, -722, -723, -724, -726, to prove replies reach the panel (only -725 is proven) | Matloob | — | Open |

### P1 — Fix what the first real chat showed

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T10 | Office address / link once per chat (engine.py:1235 checks only the current reply); record `share_office_location` and `invited_to_meeting` in `LeadAiTurn.actions` | Claude | — | Done (2026-10-13) — once per chat; sent again only when asked or after 24 h; a retyped address is cut. Eval location-request 2/2; location-again 0/2 ("how do I reach there?" gets no pointer or a paraphrase); revisit with the Maps link/pin (D2) |
| T11 | `reply_en`: store only for non-English replies; move it after `reply` in the schema so it is a translation, not a plan | Claude | — | Done (2026-10-13) — reply_en after reply, kept only for non-English replies |
| T12 | Deferrals ("I will message you", typos like "massage", "later") → tentative visit + one fixed line, no new invitation; rules.py set + settle() backstop + eval | Claude | — | Done (2026-10-13) — code rule, no model call; eval defer-message 2/2, defer-massage 2/2 |
| T13 | `invites` counts refusals, not invitations; never strip a time offer after the customer said Yes | Claude | — | Done (2026-10-13) — eval yes-to-invite 2/2, yes-to-slot 2/2 |
| T14 | `{{1}}` and CUSTOMER NAME = the person's first name, not the lead title ("Bayut WhatsApp \| Md Sumon"); fallback when empty. Cursor: C1. Claude: the engine strips a leftover prefix too | Cursor (C1) + Claude | — | Done (2026-10-13) — Cursor C1 + C8; the engine also cleans portal titles and Md/Mohd |
| T15 | Customer messages never reach the Bitrix timeline: queue `mirror_message` on commit (`crmlink/signals.py:36`; affects the whole inbox) | Claude (shared) | — | Done (2026-10-13) — after the deploy 8 of 9 inbound messages mirrored, against 8 of 106 the hour before |
| T16 | Booking, broker and handover alerts reach Matloob (Bitrix 2311) as well as the chat owner; stop belling a CRM responsible who cannot open the chat | Claude | — | Done (2026-10-13) — `alert_bitrix_user_ids` = 2311 (`ops/wa.sh leadai-alert-ids`) |
| T17 | Eval cases from chat 35283: location request, deferral, bare Yes, repeated address; replay the address append in `outgoing()` | Claude | — | Done (2026-10-13) — 54 scenarios; 97.2% on the draft, 95.4% on the deployed image |

| T18 | Code guard: a customer's own exact time inside office hours ("Can I come Wednesday at 5 pm?") is confirmed even when the model answers tentative. `probe-leadai-turn` came back tentative in 1 of 3 runs on 2026-10-13 | Claude | — | Done (2026-10-14) — `upgrade_exact_time` live. probe-leadai-turn 19/19 three times, "upgraded": true. Fixed two false hedges on the way: a size or price after around/about/from ("around 400 sq ft") and "open my shop" |
| T19 | An Urdu-script customer gets an Urdu-script reply. In eval `lang-urdu` the model answered in English or Roman Urdu in 3 of the last 4 runs. The model input is byte-identical to batch 1, where it passed 4/4, so this is model variance, not a code change. Guard: when the reply's script is not the customer's, one corrective retry, as for a refused slot | Claude | — | Open |
| T56 | The model copies SHOPS_SYSTEM's MATCH example: "For a mobile shop, Type 1 is perfect" was sent to a vape business and in a broker chat. Make the example generic and add a code guard that fills in the customer's own business | Claude | — | Open |

### P2 — The shops conversation (Bot 2)

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T20a | `LeadAiCampaign.playbook` (`general` / `ic_shops`, default `general`) + migration; `lane.mark_campaign(campaign, playbook="general")`; a retry inherits the playbook. Ship first, backward compatible | Claude | — | Done (2026-10-13) — live (e184492, migration 0003). **Cursor: C2's Django part can go now** |
| T20b | The popup "Script" choice and its pass-through to `mark_campaign` (C2) | Cursor | T20a | Open |
| T21 | Shop facts, brand, persona and agent name editable in AI settings, fed into the context; allow-list the PDF amounts in `clean_reply` | Claude | D1, D3 | Done (2026-10-14) — `shops_facts`, `brand_name` (AR Properties) and `viewing_agent_name` in AI settings. Defaults are the build-pack facts; Matloob edits the final rents there |
| T22 | Shops prompt: old-lead mode, react first, honesty line with brand, real urgency only, the PDF objection answers, unknowns → "our agent will confirm at the viewing" + note, no sentence twice (code guard) | Claude | Q4 | Done (2026-10-14) — SHOPS_SYSTEM with its own cache key; FACTS, MATCH, FREE/TAKEN SLOTS in the context; react first, honesty line, objection lines, unknowns get "our agent will confirm" + notes; a sentence never sent twice |
| T23 | First reply after Template A is the fixed "Is the shop for yourself, or are you checking for a client?" (code-written) | Claude | Q4 | Done (2026-10-14) — code-written, 6 languages, no model call |
| T24 | Broker: the exact hand-off line; a **Broker** label on the chat, shown in the Lead AI list and thread (filterable); bot silent until Resume; alert to Matloob with the number and the campaign; Bitrix marker once C3 gives the field | Claude (+ Cursor field) | — | Done (2026-10-14) — label, paused until Resume, Brokers filter, alert to 2311, the build pack's line; Bitrix Purpose 2467 + Bot Status 2479 through C6 |
| T25 | "Not now" → "Should I check back with you in a month?" → 30-day Template B or lost | Claude | Q9, Q10 | Partly done (2026-10-14) — the check-back question; a yes stores the follow-up date and shows a chip, a no is lost "1". Sending Template B on that date is T63 |
| T26 | "Stop messages" (button or text) → "Done, you won't receive more messages from us." + global opt-out (T60) | Claude | Q8 | Done for the chat (2026-10-14) — the build pack's line + WhatsApp Opt-out 2482 / Bot Status 2481 through C6. The registry across every number is T60 |
| T27 | Already rented → congratulate, ask about a second shop or a referral → lost "already rented" | Claude | Q10 | Done (2026-10-14) — congratulation + second-shop question; a no then is lost "1", reason "already rented" |
| T28 | Old-lead context: lead creation date and CRM notes (as escaped data); never mention the age of the inquiry or "our database" | Claude | — | Open |
| T29 | Silent client: one nudge after 2 h (about their business), one at 10:30 next day, inside the window; then a Follow-up status | Claude | Q10 | Open |

### P3 — Show the shops

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T30 | Media library tab on the Lead AI screen: per type video + up to 6 photos, office photo, order, size checks | Claude | D5 | Blocked D5 |
| T31 | The 3 types as a WhatsApp list message (row ≤24 chars, description ≤72) | Claude | D1 | Blocked D1 |
| T32 | `send_type_media`: video → photos → detail card with [Book viewing] [See other types]; route the taps | Claude | D5 | Blocked D5 |
| T33 | Discovery order per the PDF; MATCH one type from size and budget | Claude | D9 | Blocked D9 |
| T34 | Licence: ask for a copy; take an inbound photo/PDF as the licence (not a media handover); upload it to the lead | Claude + Cursor (file field) | Q4 | Blocked Q4 |

### P4 — Book the viewing

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T40 | Slot finder: 30-min grid 10:00–19:30, Mon–Sat, one client per slot, nearest free slot | Claude | Q6 | Done (2026-10-14) — 30-min grid, one client per slot in every playbook, nearest free slots; office bookings re-checked under a Postgres advisory lock (proved on Postgres) |
| T41 | Invite with two concrete free slots; code guard; eval fails an open "when" | Claude | T40 | Done (2026-10-14) — shops invitations name two free slots; an open "when" is rewritten for the day asked |
| T42 | Shop type on the booking (facts, appointment, CRM) | Claude | D1 | Done (2026-10-14) — fact shop_type; Bitrix Shop Type Wanted through C6 |
| T43 | Confirmation in the PDF format + location pin + "bring licence / EID + cheque book" + "See you at {time}" | Claude | D2, D6 | Done except the pin (2026-10-14) — the build pack's confirmation in 6 languages for shops. Address, Maps link and pin wait for D2 |
| T44 | Reschedule offers the two nearest free slots | Claude | T40 | Partly done (2026-10-14) — a move never offers its own slot and a taken time gets the two nearest free; the "Need to reschedule" tap still asks an open question |
| T45 | Reminder per the PDF (I'm on my way / Need to reschedule / Location); Location tap → pin | Claude | D4 | Blocked D4 |
| T46 | ~~Assign the lead to the shop agent on booking~~ — not needed: the shop agent is Bitrix user 1 (admin, "hold" user) and alerts go to Matloob (Q12) | — | — | Dropped (2026-10-13) |
| T47 | Agent alert on WhatsApp (later) | Claude | Q13 | Open |

### P5 — Bitrix data

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T50 | Bitrix field map and the missing fields (C3) | Cursor | — | Open |
| T51 | Write those fields whenever they change, not only at booking. Per C4, a REST `crm.lead.update` runs BP 235 on every edit (at stage 10 it clears Meeting Date & Time, plans a to-do and rewrites the title), so the writes go through a small HMAC-signed Bitrix tool that uses the CRM factory with `disableBizProc()` / `disableAutomation()` and never sends `STATUS_ID` / `ASSIGNED_BY_ID`. Cursor builds the tool, Claude calls it. Also check today's booking write (stage 10 + Meeting Date over REST) against BP 235 on a test lead | Claude + Cursor | T50 | Done (2026-10-14) — Shop Type, business, licence and Bot Status written through C6 when they change (deduped, retried). The booking's stage write is still REST until T55 |
| T52 | Bot Status set in Bitrix (Handed to agent / Broker / Opted out) silences the bot | Claude + Cursor | T50 | Open |
| T53 | mark_lost: Not Interested (`1`) or Junk (`JUNK`) per Q10, with the reason in the client's words | Claude (+ Cursor tool, T51) | T51 | Done (2026-10-14) — lost moves to "1" or JUNK through C6, reason in the customer's words |
| T54 | Each campaign reply (Yes / Not now / Stop) written to the lead | Claude | T50 | Partly done (2026-10-14) — Bot Status Qualifying on the first answer, Opted out on stop, Lost on no; a dedicated "campaign reply" field is not built |
| T55 | **Booking CRM write through the C6 `booking` action** instead of REST `crm.lead.update`, because BP 235 wipes the meeting time (C7). Keep the per-event comment; drop the old to-do mover once C9 owns the to-do | Claude | — | Open — C9 is live (`cef5a977`); next Claude batch |

### P6 — Sending

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T60 | Global opt-out by phone; every campaign path skips it; import the 279 past Unsubscribe/Stop | Claude (+ Cursor C10: the popup shows who was skipped) | — | Open |
| T61 | Create and submit on the 8 sending WABAs: `intl_city_shops_followup` (Template B, needed by the automatic follow-ups), and `intl_city_shops_reconnect` (Template A, video header) so Matloob can pick it in the popup if he wants it; reminder v2. Rents from the live shops facts, brand AR Properties, Type 1 video from D5 | Claude | — | Open |
| T62 | ~~Drip~~ — dropped (Q7, 2026-10-14): Matloob sends campaigns himself, any volume | — | — | Dropped |
| T63 | Template B once, 72 h after A, only to non-repliers; never a third | Claude | T61 | Open |
| T64 | Skip brokers and duplicates across campaigns before sending | Claude + Cursor | T50 | Open |
| T65 | First video-header send end to end on Matloob's own number with the Lead AI box | Matloob + Claude | T61 | Open |

### P7 — Prove it and launch

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T70 | Shops eval: the PDF's 8 launch-checklist cases + the chat-35283 cases; gate ≥95% over `--repeat 2` | Claude | P2–P4 | Open |
| T71 | 10 staff-phone chats on test numbers (PDF checklist) | Matloob + Claude | D8 | Blocked D8 |
| T72 | Go live at 100 a day; read every chat daily for a week; fix the prompt | Matloob + Claude | T70, T71 | Open |
| T73 | Weekly funnel: replies → viewings booked → attended → rented | Claude | — | Open |

### Later — Bot 1 (portal inquiries)

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T80 | Company API number on the PF / Bayut / Dubizzle shop ads | Matloob | — | Open |
| T81 | Lead AI lane for client-first chats on those numbers; find or create the Bitrix lead by phone; listing from the first message | Claude + Cursor | T80 | Open |
| T82 | Bot 1 "closer" prompt on top of the shops playbook | Claude | T81 | Open |

---

## Cursor's list (C1–C19)

Cursor owns these. Claim each one in its row before starting, follow CLAUDE.md for deploys (Bitrix files: `ops/bitrix.sh put`; Django: `ops/wa.sh build app` → `up app`, after checking that no campaign is running), and write a TASKS.md entry when done.

| ID | Task | Files | Status |
|---|---|---|---|
| C1 | **`{{1}}` = the person's first name** (T14). Today "Name" resolves to the lead TITLE, so customers get "Hi Bayut WhatsApp \| Md Sumon". Use NAME (first word) when it is a real name; otherwise the part of TITLE after the last `\|`. Reject phone numbers, "Missed Call…", "untitled" and empty values, and fall back to "there". `CampaignRecipient.name` must carry the same clean name, because the assistant greets with it. The deal path already strips the prefix (`a7_lead_wa.php:565`). Add cases to `campaigns/tests/test_crm_leads.py` | `ops/bitrix-aws/a7_lead_wa.php` (`a7_lead_wa_display`, :63-68, :264-269), `backend/apps/campaigns/crm_leads.py` (`detail_value`, `lead_display_name` :187-211; `renewals.py` imports it) | Done (2026-10-13) — live: portal title after the last \|, NAME's first word, else "there". Tests 25+11 OK. Containers `d53a6a89`, PHP `e64b7660` (401). |
| C2 | **"Script" choice beside the Lead AI box** (T20b), shown only while the box is ticked: `General` / `International City shops`. Payload field `lead_ai_playbook` = `general` \| `ic_shops`; the PHP forwards it after checking it is one of the two; `campaigns/views.py` (:228, :282) passes it to `send_from_leads` / `send_renewals`, which call `mark_campaign(campaign, playbook=…)`. Deploy the Django part only after Claude's T20a is live | `ops/bitrix-aws/a7_lead_wa.js` (:766-786, :1385), `a7_lead_wa.php` (:1016), `a7_renewals_wa.js/.php`, `backend/apps/campaigns/views.py`, `crm_leads.py` (:348-404), `renewals.py` (:277-369) | Done (2026-10-13) — Django live: views `883c6d98`, renewals `7623a8f2`, all four containers. `mark_campaign` accepts playbook. Bitrix JS/PHP already matched. |
| C3 | **Bitrix field map** (T50, Q10). Reuse: SOURCE_ID, Purpose `UF_CRM_LEAD_1737031634747` (for Broker), business activity, `UF_CRM_A7_AI_TRADE_LICENSE_STATUS` (add DED / Trakhees / New licence), Meeting Date & Time. Create on leads: **Shop Type Wanted** (Type 1 / Type 2 / Type 3 / Not sure), **Trade License File** (file), **Bot Status** (New / Qualifying / Viewing booked / Handed to agent / Broker / Lost / Opted out), **WhatsApp Opt-out** (Yes/No). Put them on the lead form. Write every UF id and enum id here under "Bitrix field map". Also list the STATUS_ID and stage-required fields of JUNK, Reject and "Not interested" (UC_RYQD1Z), so Matloob can pick the lost stage | Bitrix (`ops/bitrix-aws/`), this board | Done (2026-10-13) — fields 2665–2668 live; licence 2455–2457; Broker 2467; section `a7_shops_bot` on the common form and layouts 1, 2 and 6. |
| C4 | **Field-only lead updates** (needed by T51). Check what BP 235 and the lead-shift timer do when a lead already in stage 10, or held by user 1, gets a `crm.lead.update` that changes fields only. If that plans another to-do or moves the lead, say how to avoid it. Write the answer here | Bitrix robots/BP, `a7_lead_shift.php` | Done (2026-10-13) — stage 10 REST update clears the meeting time and plans another to-do; write fields with bizproc disabled. |
| C5 | **Secrets out of the source** (low priority). `ops/bitrix-aws/a7_tl_phone_mask.config.php`: change the phone-mask password on the box, then `git rm --cached` the file and commit a `.example`. The 3CX tools (`a7_3cx_click_to_call*.php`, `a7_3cx_ai_recording_analyzer.php`) hard-code an OpenAI key, Bitrix webhook tokens and 3CX secrets: move them into an ignored config file. Both are already in `.gitignore` | `ops/bitrix-aws/` | Done (2026-10-13) — phone-mask password changed on the box; config untracked; 3CX secrets read from `a7_3cx.config.php`. |
| C6 | **Lead fields tool for the assistant** (T51, T52, T53). See *Lead fields tool contract* below; write the final URL and anything you changed there | NEW `ops/bitrix-aws/a7_leadai_fields.php` → `/home/bitrix/www/bitrix/tools/` | Done (2026-10-13) — GET 405, bad signatures 401, unknown field 400. Test lead 79544: shop+bot, title/stage/meeting unchanged, to-dos 0, lost to 1 with the comment, PDF stored, lead deleted. |
| C7 | **Today's booking write vs BP 235** (before go-live). On a confirmed booking, `backend/apps/leadai/assistant/crm.py` sends one REST `crm.lead.update`: `STATUS_ID=10`, Meeting Date & Time, Mode Offline, a few empty-only fields. It then moves or closes the to-do the assistant caused. Per C4, BP 235 at stage 10 clears the meeting time and plans a to-do. Replay exactly that payload on a **test lead** and report: is the meeting time kept, how many to-dos exist after, what the title becomes. If BP 235 breaks it, propose the fix here: either the booking goes through the C6 tool with a separate stage move, or BP 235 skips leads whose Bot Status is "Viewing booked" | Bitrix BP 235, read `crm.py` | Done (2026-10-13) — lead 79545: meeting wiped, one to-do due now, title became "Personal \| Sumon Khan". Lead and viewing item deleted. |
| C8 | **Honorifics in `{{1}}`** (C1 follow-up). When the chosen first word is a prefix and another word follows, use the next word: "Md Sumon" → "Sumon". The prefixes are Md, Mohd, Muhammad, Mohammad, Mohammed, Muhammed, Mohamed, Dr, Mr, Mrs, Ms, Miss, Engr and Eng, with or without a dot. Same rule in PHP and Django, with tests. The assistant's own greeting gets the same rule on Claude's side | `a7_lead_wa.php`, `crm_leads.py`, `tests/test_crm_leads.py` | Done (2026-10-13) — "Md Sumon" greets as Sumon. Tests 29+11 OK. PHP `f16450ca` (401). Containers `cd4ec0e5`. |
| C9 | **Booking through the C6 tool** (fixes C7, before any shop campaign). Add a `booking` action to `a7_leadai_fields.php`, with the same signature and bizproc/automation off: `{"lead_id": …, "booking": {"meeting_at": "2026-11-02T16:30:00+04:00", "mode": 42, "event": "confirmed" \| "rescheduled" \| "cancelled"}, "fields": {…}}`. `confirmed` / `rescheduled` set `STATUS_ID=10` + Meeting Date & Time + Mode, Bot Status = Viewing booked (2477), and create or move **one** "Viewing/Meeting" to-do for the lead's responsible at the meeting time (not "now"). Return its id. `cancelled` closes that to-do and leaves the stage. The title is never touched. BP 235 stays as it is. Prove it on a test lead: time kept, exactly one to-do at the meeting time, title unchanged. Then Claude switches `crm.py` to it (T55) | `a7_leadai_fields.php` | Done (2026-10-13) — lead 79557: time 16:30 kept, one to-do at that time, title unchanged; reschedule moved the same to-do; cancel closed it and left stage 10. Lead deleted. |
| C10 | **Skip the leads the bot must not message** (T60, T64; before the first shop campaign). In every CRM popup with the Lead AI box, leave out leads whose Bot Status is Broker (2479), Lost (2480) or Opted out (2481), or whose WhatsApp Opt-out is Yes (2482). Also leave out a phone already in the same campaign (exists today) or reached by the same template in the last 30 days. Show the count beside the existing "missing a phone" note ("3 left out: opted out 1, broker 1, lost 1"), so the agent sees why 100 selected became 97. Do it where you already build the recipient list (PHP and/or `crm_leads.py`), with tests. Claude's global opt-out registry (T60) adds the phones that opted out in WhatsApp later; leave a hook for it | `a7_lead_wa.php/.js`, `crm_leads.py`, `tests/test_crm_leads.py` | Done (2026-10-13) — Lead AI skips broker, lost, opted out and WhatsApp opt-out Yes, plus the same template in 30 days. Popup: "3 left out: opted out 1, broker 1, lost 1". Tests 37+11 OK. PHP `527920b6` (401), JS `dd959359` (200). Four services up. No WhatsApp sent. |
| C11 | **An opt-out holds on every campaign, not only Lead AI** (C10 follow-up, Q8). Today a lead whose WhatsApp Opt-out is Yes (2482), or whose Bot Status is Opted out (2481), still gets an ordinary campaign when the Lead AI box is off. "Stop" has to mean stop everywhere: WhatsApp policy and Q8. Apply those two to **every** CRM popup send (box on or off; Leads, Owner Data, Deals, Contacts, Renewals) and the Excel/bulk campaigns, with the same left-out count. Broker and Lost stay Lead AI-only. Keep the `phones_blocked_by_registry` hook on the shared path, so Claude's T60 registry blocks phones everywhere too | `crm_leads.py`, `renewals.py`, `bulk.py` (if it builds recipients), popup PHP/JS, tests | Done (2026-10-13) — Opt-out (2482 / 2481) is skipped on every send, box on or off, including Excel. Broker and Lost stay Lead AI only. Tests 41+12 OK. PHP `c3750a0e` (401), lead JS `47984536` (200). Four services up. No WhatsApp sent. |
| C12 | **Bot Status set by a person in Bitrix reaches the bot** (T52). Add a lead-update handler in the a7 includes. It fires when a **person** (not the C6 tool: have the tool flag its own saves so the handler skips them) changes `UF_CRM_A7_BOT_STATUS` to 2478 Handed to agent, 2479 Broker, 2480 Lost or 2481 Opted out, or `UF_CRM_A7_WA_OPT_OUT` to 2482 Yes. It POSTs JSON to Django `https://wa.srv1802669.hstgr.cloud/api/leadai/bitrix/bot-status/`.<br>**Headers:** `X-Leadai-Ts` and `X-Leadai-Sign` = hex HMAC-SHA256(same secret, `"leadai-botstatus." . ts . "." . body`).<br>**Body:** `{"lead_id": 123, "bot_status": 2478, "wa_opt_out": 2482 or null, "changed_by": 2311, "at": "2026-10-13T12:00:00+04:00"}`.<br>**Behaviour:** 3 s timeout, never blocks or fails the save, one log line on error. Django's endpoint comes in Claude's batch 2b (T52); until then it answers 404, which the handler only logs.<br>**Proof:** on a test lead, a person's change sends one signed POST, and a C6 write sends none | a7 lead-update handler (`ops/bitrix-aws/`), `a7_leadai_fields.php` (self-flag) | Done (2026-10-13) — lead 79571: a person's Handed-to-agent change logged one POST http=404; Qualifying and a C6 Broker/opt-out write logged none. Lead deleted. Handler `cf8fbefc`, fields tool `09d7e791`. |
| C13 | **See the popups in a real browser, with every send blocked** (nobody has clicked them since C1, C2, C10 and C11). Use Playwright as an admin on the live CRM. Load the Leads list first, then guard: an in-page fetch/XHR wrapper plus `page.route`, so no queue request leaves; see the playwright-bitrix-send-guard note in CLAUDE memory/TASKS.md 2026-10-08. Check on Leads, Owner Data, Deals, Contacts and Renewals:<br>- **Script dropdown:** appears only while the Lead AI box is ticked, and defaults to General.<br>- **Payload:** the intercepted body carries `lead_ai_playbook`.<br>- **Left-out line:** shows the right counts on a selection that holds a test lead with Bot Status Broker and one with WhatsApp Opt-out Yes (create both, delete after).<br>- **Greeting:** `{{1}}` previews the person's first name ("Sumon", not "Bayut WhatsApp \| …").<br>Screenshots in the scratchpad, nothing sent (prove it: campaign count before = after) | Playwright, test leads | Done (2026-10-13) — Playwright as admin, list loaded before the send guard. Leads: `2 left out: opted out 1, broker 1`, preview `Hi Sumon`, payload `lead_ai_playbook=general`. Same Script/payload/greeting on Owner Data, Deals, Contacts, Renewals. Campaigns 397 before and after. Leads 79574 and 79575 deleted. Screenshots in `files/temp/c13-popups/shots/`. |
| C14 | **The send button must count what will really go** (seen in C13's `leads.png`). With "2 selected · 0 can be messaged · 2 left out" the button still reads "Queue 2 messages to Lead AI". The button counts only the leads that can be messaged, and is disabled at 0 ("Nothing to send: all left out"). All five popups. A send blocked by the guard is fine for the proof | `a7_lead_wa.js`, `a7_renewals_wa.js` | Done (2026-10-13) — Leads, box off: `Queue 1 message` (broker still sendable, opt-out left out). Box on: button disabled, `Nothing to send: all left out`, line `2 left out: opted out 1, broker 1`. Deals/Contacts `Queue 1 message to Lead AI`, Renewals `Send 1 message to Lead AI`, Owner at 0 disabled with the same sentence. Sends blocked. Campaigns 397 before and after. JS `040c73cb`, `5075d2c3`. Test rows deleted. |
| C15 | **A ready-made filter for the shop leads Matloob sends to** (he sends campaigns himself, Q7). In the Bitrix Leads list, a shared filter preset **"IC shops — ready for Lead AI"**: Community = International City; the shop / commercial interest (find the field that marks it: property type, Client Type, Purpose or the source; say on the board which one and why); Bot Status empty, New or Qualifying; WhatsApp Opt-out not Yes; a phone present. Add the columns **Bot Status**, **Shop Type Wanted** and **WhatsApp Opt-out** to the admins' Leads grid. Prove it: the preset's count equals a direct SQL count with the same conditions | Bitrix filters / grid, this board | Done (2026-10-14) — preset "IC shops — ready for Lead AI" uses Unit Type = Shop. Preset count 34, SQL count 34. Columns on all 12 admin grids. |
| C16 | **Say it loudly when the gateway runs out of credit, and stop burning retries** (2026-10-14: "Insufficient credits … Available credits are 1.8829" failed 55 of campaign 408's 58 sends and most other sends). When a send fails with that error:<br>- **Campaign retries:** the recipient waits as "no credit", is retried only after credit returns, and never becomes "exhausted" for it.<br>- **Banner:** the Official panel shows a red banner "WhatsApp credit is out — messages are not going".<br>- **Bell:** a Bitrix bell goes to the Lead AI alert users (2311), at most once an hour.<br>If the gateway has a balance endpoint, poll it hourly and warn below a threshold (setting, default 50). Tests; deploy the CLAUDE.md way | `backend/apps/campaigns/**`, `backend/apps/gateway/**`, panel banner (new module) | Done (2026-10-14) — insufficient-credit waits (never exhausted); banner + `/api/gateway/credit/`; hourly poll; bell ≤1/h. Tests 9 OK. gateway.0003 live. Four services up. |
| C17 | **Remove the dead `backfill_placeholder_bodies.delay()`** in `backend/apps/gateway/tasks.py:127`, with its `cache` import and the `if cache.add(...)` line (flagged 2026-10-08). After every restart it raises a NameError on the first webhook and that event is retried 30 s later. Prove: after a deploy, no NameError in `ops/wa.sh logs app worker 400` | `backend/apps/gateway/tasks.py` | Open |
| C18 | **No dead verbs in `ops/wa.sh`**: 11 verbs call `ops/catalog` probes deleted on 2026-09-29. Remove those verbs and their usage lines (or restore a probe if it is still wanted; say which). `bash -n` clean; each remaining catalog verb's script exists | `ops/wa.sh` | Open |
| C19 | **Report only: lead and contact names that hold a portal title** ("Bayut WhatsApp \| Sabeer" in NAME). Count them per source and per field (lead NAME, contact NAME). Show 10 examples and the clean value C1's rule would give. Propose a one-off fix. **No CRM writes**: Matloob decides | read-only Bitrix SQL, this board | Open |

### Lead fields tool contract (C6)

- **Endpoint.** `POST /bitrix/tools/a7_leadai_fields.php`, JSON body.
  - GET gives 405.
  - Body at most 8 MB.
  - The signature is checked before the Bitrix prolog, like `a7_leadai_notify.php`.
- **Signature.** Same secret as `a7_leadai_notify.php` (the `CRM_LEAD_WA_SECRET` shared with Django), same headers.
  - `X-Leadai-Ts`: unix seconds, within 300 s.
  - `X-Leadai-Sign` = hex HMAC-SHA256(secret, `"leadai-fields." . ts . "." . body`).
  - The `leadai-fields.` prefix means a notify signature can never be replayed here.
- **Body.**
  ```json
  {
    "lead_id": 73688,
    "fields": {"UF_CRM_A7_SHOP_TYPE": 2471, "UF_CRM_A7_BOT_STATUS": 2476},
    "only_if_empty": ["UF_CRM_A7_AI_BUSINESS_ACTIVITY"],
    "license_file": {"name": "licence.pdf", "content_base64": "..."},
    "lost": {"status_id": "1", "reason": "the customer's own words"},
    "comment": "optional timeline comment"
  }
  ```
- **Fields: allow-list only.** Unknown codes or enum ids give 400.
  - **Codes:** the C3 fields, Business activity, Trade license status, Purpose, Meeting Date & Time.
  - **Purpose:** only the value 2467 (Broker).
  - **`only_if_empty`:** codes listed there are written only while the lead's value is empty, so a value an agent typed is never overwritten.
- **Write.** Through the CRM factory with `disableBizProc()` and `disableAutomation()`.
  - Never touch `STATUS_ID` or `ASSIGNED_BY_ID`, except the `lost` move.
  - The `lost` move accepts only `1` or `JUNK` (Q10). Whether it runs with BP/automation on or off is your call; write the reason here.
  - The reason goes on the lead as a timeline comment, "Lead AI: …".
- **Licence file.** PDF, JPEG or PNG, checked by magic bytes; at most 5 MB decoded; stored on `UF_CRM_A7_TRADE_LICENSE_FILE`.
- **Response.** `{"ok": true, "lead_id": 73688, "updated": [...], "skipped": [...], "lost": "1" | null}`.
  - 400: bad JSON, field or enum.
  - 401: signature.
  - 404: no such lead.
  - 405: method.
- **Proof before Done.**
  - `php -l` passes.
  - Unsigned, wrong and old signatures each give 401.
  - GET gives 405; an unknown field gives 400.
  - On a **test lead** (deleted afterwards): writing Shop Type + Bot Status creates no new to-do and leaves title, stage and Meeting Date unchanged.
  - A `lost` move to `1` puts the comment on the lead.
  - A PDF lands on the file field.

**Shipped.** `POST https://crm.a7grouprealestatedxb.com/bitrix/tools/a7_leadai_fields.php`

The licence is sent as `license_file`, not as a file id inside `fields` (that code returns 400). The file id is written on the lead column because the CRM item save drops it; that write does not start BP 235. The `lost` move also runs with bizproc and automation off: BP 235 on `JUNK` and `1` would create a Lead Pool item and rewrite the title. The stage still changes, and the reason is the timeline comment `Lead AI: …`.

### Bitrix field map (Cursor fills in, C3)

| Field | UF id | Enum ids |
|---|---|---|
| SOURCE_ID | system field, no UF | lead source statuses, not a UF enum |
| Purpose (Broker goes here) | `UF_CRM_LEAD_1737031634747` id 1351 | 804 I'm Investor, 805 I want for myself, 806 I'm Agent, **2467 Broker** (added) |
| Business activity | `UF_CRM_A7_AI_BUSINESS_ACTIVITY` id 2399 | text, no enums |
| Trade license status | `UF_CRM_A7_AI_TRADE_LICENSE_STATUS` id 2400 | 2159 Yes, 2160 No, **2455 DED**, **2456 Trakhees**, **2457 New licence** (added) |
| Meeting Date & Time | `UF_CRM_1731838813769` id 122 | datetime, no enums. Required on stage 10 |
| Shop Type Wanted | `UF_CRM_A7_SHOP_TYPE` id 2665 | 2471 Type 1, 2472 Type 2, 2473 Type 3, 2474 Not sure |
| Trade License File | `UF_CRM_A7_TRADE_LICENSE_FILE` id 2666 | file, no enums |
| Bot Status | `UF_CRM_A7_BOT_STATUS` id 2667 | 2475 New, 2476 Qualifying, 2477 Viewing booked, 2478 Handed to agent, 2479 Broker, 2480 Lost, 2481 Opted out |
| WhatsApp Opt-out | `UF_CRM_A7_WA_OPT_OUT` id 2668 | 2482 Yes, 2483 No |

Lost stages (Q10), read live from `b_crm_status` (`ENTITY_ID='STATUS'`) and `b_crm_field_attr` (lead = entity type 1, every row is type 3):

| Stage | STATUS_ID | Semantics | Required fields |
|---|---|---|---|
| Junk Lead | `JUNK` | F (lost) | none |
| Not Interested | `1` | F (lost) | none |
| Lead Reject | `9` | F (lost) | `UF_CRM_1734162646510` Reason of Reject (phase 9 only) |
| Not interested | `UC_RYQD1Z` | empty (still an open stage) | none |

There is no stage named exactly "Reject". The failed one with a required field is **Lead Reject (`9`)**. `UC_RYQD1Z` is a different "Not interested" and is not a lost stage.

## IC shops filter (C15)

The shared Leads preset **IC shops — ready for Lead AI** uses **Unit Type** `UF_CRM_1731838348693` = **Shop** (enum 384). That is the only lead field whose value is the word Shop. Client Type is Buyer / Seller / Tenant / owner (4,195 of the 5,010 International City leads are Tenant, almost all with an empty unit type). Purpose is investor / myself / agent / broker. Property Segment Commercial is 26 leads and is not the shop list. Community is the text field `UF_CRM_1770537051525`, and every Shop-typed lead in it is International City (35, of which 34 have a phone).

The preset also requires Community = International City, Bot Status empty or New (2475) or Qualifying (2476), WhatsApp Opt-out empty or No (not Yes 2482), and a phone. It is a common preset and is on each administrator's own filter list. Bot Status, Shop Type Wanted and WhatsApp Opt-out are columns on all 12 administrators' saved Leads grids. Preset count 34, SQL count 34.

## Field-only lead updates (C4)

Checked live BP **235 Lead Automation** (`AUTO_EXECUTE=3`, active: runs on create and on every edit) and `a7_lead_shift.php`. There are no CRM automation-robot rows for leads. A field-only `crm.lead.update` does not by itself change the stage or the owner. It does start BP 235, and the template looks at the stage the lead is **already** in.

**Already in stage 10.** The "Viewing/Meeting" branch matches `STATUS_ID = 10`, then:
- clears Meeting Date & Time (`UF_CRM_1731838813769`)
- plans another to-do, subject "Viewing/Meeting", responsible = the current assignee, deadline = that same field (just emptied, so it is due now)
- adds a timeline comment and starts another workflow

The first step of the template, before any stage check, also rewrites `TITLE` to `{SOURCE_ID} | {NAME} {LAST_NAME}` on every edit. That is where "Bayut WhatsApp | Md Sumon" keeps coming back.

**Held by user 1.** BP 235 never reads `ASSIGNED_BY_ID`. User 1 does not turn the template off. A lead in stage 10 gets the to-do above whoever owns it. A lead still in `NEW` gets the "New Lead" bell. A lead in `UC_MJDO60` gets the "Assigned" bell.

**Lead-shift timer.** It is a poll, not a handler on the update. Intake is `STATUS_ID='NEW'` and the owner is on the intake roster. The other pass is only `NEW`, `UC_MJDO60` and `12`. Stage 10 is in neither query, so the timer will not move a stage-10 lead because a field changed. `a7_lead_shift_assign` is the place that takes a `NEW` lead off user 1 and sets stage `UC_MJDO60`. A field write does not call it. A shops lead that is still `NEW` and still on user 1 can still be handed off on a later timer run, because that is what the timer is for.

**How T51 should write fields.** Use the CRM factory update with `disableBizProc()` and `disableAutomation()`, the same two calls `a7_lead_shift_assign` already makes, and do not send `STATUS_ID` or `ASSIGNED_BY_ID`. REST `crm.lead.update` cannot switch the template off. On a lead in stage 10 it will wipe the meeting time and plan another to-do.

## Booking write vs BP 235 (C7)

Replayed `booking_fields()` on test lead 79545 (deleted afterwards). One REST `crm.lead.update`: `STATUS_ID=10`, Meeting Date `2026-11-02T16:30:00+04:00`, Mode `42`. REST returned ok.

- The meeting time was **not** kept. The column was empty.
- **One** to-do, subject Viewing/Meeting, deadline 13/10/2026 10:11:42 am (when the template ran, not 16:30).
- The title became `Personal | Sumon Khan`. It had been `ZZ C7 booking test delete`.
- The stage did become 10. Mode 42 stayed.
- The template also created Viewing/Meeting item 639 with that title. That item was deleted.

Writing the time through C6 and then moving to stage 10 by the same REST call still hits this branch, so the time is wiped again and another to-do is due now. Moving the stage inside C6 with bizproc off keeps the time and the title, and plans no to-do. The assistant currently looks for the to-do this template just planned and moves its deadline.

**Fix to make:** in BP 235's stage-10 branch, skip "Empty Viewing/Meeting" and the new to-do when Bot Status is already Viewing booked (`UF_CRM_A7_BOT_STATUS` = 2477). The assistant writes the meeting, the mode and that status through the C6 tool first. A person who moves a card to stage 10 without that status still gets the to-do. The title rewrite (`{source} | {name}`) still runs on the REST stage change. Stopping that as well means the stage move also goes through C6 with bizproc off, and the assistant has to plan the to-do itself.

## Requests (one side asking the other)

- **Claude → Cursor: the 2026-10-13 BUILD LOCK is released (2026-10-14 ~05:50 UTC).** Batch 2a and 2a.1 are live and migrated (leadai 0004), and the build context equals the repo again. Normal deploys can resume.

- Claude → Cursor: C1 and C2 touch `crm_leads.py` / `a7_lead_wa.*` (your 2026-10-12 work), so they are on your list. Claude will not edit those files.
- Cursor → both: `ops/wa.sh test` no longer calls pytest (the image has none, and the old verb exited 0). It runs `manage.py test` in a one-off container with `settings_livetest`, same locks as `leadai-tests`.

## Known risks

- **Phone-mask password was in git.** The live password was changed on 2026-10-13 and `a7_tl_phone_mask.config.php` is no longer tracked. The old password is still in git history. The 3CX tools read secrets from `a7_3cx.config.php`, which is gitignored.
- **Broken probes:** 11 `ops/catalog` probes were deleted by another session, and their `ops/wa.sh` verbs now fail.
- **Shops script changes old rules:** it reverses several of the 2026-10-09 rules, so eval scenarios `shop-activity`, `shop-rent` and `shop-no-licence` must change with it.
