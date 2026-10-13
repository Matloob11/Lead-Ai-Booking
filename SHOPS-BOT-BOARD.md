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
| Q7 | Sending | default: automatic drip ~100/day, 11:00–18:00 Mon–Sat, spread over the sending numbers; Template B once after 72 h to non-repliers |
| Q8 | Opt-out | default: block the phone on every number and campaign (Sara too); import the 279 past Unsubscribe/Stop |
| Q9 | "Not now" | default: "check back in a month?" → yes: Template B after 30 days; no: lost |
| Q10 | Which Bitrix stage is "lost" | **open**: Cursor lists the stage ids (C3), Matloob picks |
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
| D2 | Office: final address, Google Maps link, pin latitude/longitude | Matloob sends |
| D3 | Brand + the `{{2}}` name in "this is {{2}} from {{3}}" | **AR Properties**; `{{2}}` typed per campaign: "Malik" or "Matloob" (template sample: Malik) |
| D4 | Sending numbers | **decided**: active 971 numbers, not coexistence, not assigned: 971581058719, -720, -721, -722, -723, -724, -725, -726 (Coastline Properties / Blue Brick). 971507563104 left out: in daily use (1,755 inbound) with no templates. Only -725 has a proven inbound webhook; the other 7 have never received a message, so each gets one test message before use. `ic_shops_followup` is approved on all 8; `a7_leadai_meeting_reminder` on none (T05) |
| D5 | Media: per type 1 MP4 under 16 MB (30–60 s) + up to 6 photos; office-front photo; Type 1 walkthrough for Template A's header | Matloob sends |
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
| T05 | Get `a7_leadai_meeting_reminder` approved on the 8 sending WABAs (D4); the submit command takes only numbers with an agent, so it also takes the sending numbers | Claude | — | Open |
| T06 | Paste the Maps link and coordinates in Lead AI → AI settings | Matloob | D2 | Blocked D2 |
| T07 | One test message from a phone to each of 971581058719, -720, -721, -722, -723, -724, -726, to prove replies reach the panel (only -725 is proven) | Matloob | — | Open |

### P1 — Fix what the first real chat showed

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T10 | Office address / link once per chat (engine.py:1235 checks only the current reply); record `share_office_location` and `invited_to_meeting` in `LeadAiTurn.actions` | Claude | — | Open |
| T11 | `reply_en`: store only for non-English replies; move it after `reply` in the schema so it is a translation, not a plan | Claude | — | Open |
| T12 | Deferrals ("I will message you", typos like "massage", "later") → tentative visit + one fixed line, no new invitation; rules.py set + settle() backstop + eval | Claude | — | Open |
| T13 | `invites` counts refusals, not invitations; never strip a time offer after the customer said Yes | Claude | — | Open |
| T14 | `{{1}}` and CUSTOMER NAME = the person's first name, not the lead title ("Bayut WhatsApp \| Md Sumon"); fallback when empty. Cursor: C1. Claude: the engine strips a leftover prefix too | Cursor (C1) + Claude | — | Open |
| T15 | Customer messages never reach the Bitrix timeline: queue `mirror_message` on commit (`crmlink/signals.py:36`; affects the whole inbox) | Claude (shared) | — | Open |
| T16 | Booking, broker and handover alerts reach Matloob (Bitrix 2311) as well as the chat owner; stop belling a CRM responsible who cannot open the chat | Claude | — | Open |
| T17 | Eval cases from chat 35283: location request, deferral, bare Yes, repeated address; replay the address append in `outgoing()` | Claude | — | Open |

### P2 — The shops conversation (Bot 2)

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T20a | `LeadAiCampaign.playbook` (`general` / `ic_shops`, default `general`) + migration; `lane.mark_campaign(campaign, playbook="general")`; a retry inherits the playbook. Ship first, backward compatible | Claude | — | Open |
| T20b | The popup "Script" choice and its pass-through to `mark_campaign` (C2) | Cursor | T20a | Open |
| T21 | Shop facts, brand, persona and agent name editable in AI settings, fed into the context; allow-list the PDF amounts in `clean_reply` | Claude | D1, D3 | Blocked D1 |
| T22 | Shops prompt: old-lead mode, react first, honesty line with brand, real urgency only, the PDF objection answers, unknowns → "our agent will confirm at the viewing" + note, no sentence twice (code guard) | Claude | Q4 | Blocked Q4 |
| T23 | First reply after Template A is the fixed "Is the shop for yourself, or are you checking for a client?" (code-written) | Claude | Q4 | Blocked Q4 |
| T24 | Broker: the exact hand-off line; a **Broker** label on the chat, shown in the Lead AI list and thread (filterable); bot silent until Resume; alert to Matloob with the number and the campaign; Bitrix marker once C3 gives the field | Claude (+ Cursor field) | — | Open |
| T25 | "Not now" → "Should I check back with you in a month?" → 30-day Template B or lost | Claude | Q9, Q10 | Blocked Q9 |
| T26 | "Stop messages" (button or text) → "Done, you won't receive more messages from us." + global opt-out (T60) | Claude | Q8 | Blocked Q8 |
| T27 | Already rented → congratulate, ask about a second shop or a referral → lost "already rented" | Claude | Q10 | Blocked Q10 |
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
| T40 | Slot finder: 30-min grid 10:00–19:30, Mon–Sat, one client per slot, nearest free slot | Claude | Q6 | Blocked Q6 |
| T41 | Invite with two concrete free slots; code guard; eval fails an open "when" | Claude | T40 | Open |
| T42 | Shop type on the booking (facts, appointment, CRM) | Claude | D1 | Blocked D1 |
| T43 | Confirmation in the PDF format + location pin + "bring licence / EID + cheque book" + "See you at {time}" | Claude | D2, D6 | Blocked D2 |
| T44 | Reschedule offers the two nearest free slots | Claude | T40 | Open |
| T45 | Reminder per the PDF (I'm on my way / Need to reschedule / Location); Location tap → pin | Claude | D4 | Blocked D4 |
| T46 | ~~Assign the lead to the shop agent on booking~~ — not needed: the shop agent is Bitrix user 1 (admin, "hold" user) and alerts go to Matloob (Q12) | — | — | Dropped (2026-10-13) |
| T47 | Agent alert on WhatsApp (later) | Claude | Q13 | Open |

### P5 — Bitrix data

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T50 | Bitrix field map and the missing fields (C3) | Cursor | — | Open |
| T51 | Write those fields whenever they change, not only at booking | Claude | T50 | Open |
| T52 | Bot Status set in Bitrix (Handed to agent / Broker / Opted out) silences the bot | Claude + Cursor | T50 | Open |
| T53 | mark_lost: move to the lost stage with the reason in the client's words | Claude | Q10 | Blocked Q10 |
| T54 | Each campaign reply (Yes / Not now / Stop) written to the lead | Claude | T50 | Open |

### P6 — Sending

| ID | Task | Owner | Needs | Status |
|---|---|---|---|---|
| T60 | Global opt-out by phone; every campaign path skips it; import the 279 past Unsubscribe/Stop | Claude (+ Cursor: popup shows who was skipped) | Q8 | Blocked Q8 |
| T61 | Create and submit `intl_city_shops_reconnect` (video header), `intl_city_shops_followup`, reminder v2 on the sending WABAs | Claude | D4, D5 | Blocked D4 |
| T62 | Drip: ~100 a day, 11:00–18:00 Dubai, Mon–Sat, rolls over, visible queue and cancel | Claude | Q7 | Blocked Q7 |
| T63 | Template B once, 72 h after A, only to non-repliers; never a third | Claude | Q7, T61 | Blocked Q7 |
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

## Cursor's list (C1–C5)

Cursor owns these. Claim each one in its row before starting, follow CLAUDE.md for deploys (Bitrix files: `ops/bitrix.sh put`; Django: `ops/wa.sh build app` → `up app`, after checking that no campaign is running), and write a TASKS.md entry when done.

| ID | Task | Files | Status |
|---|---|---|---|
| C1 | **`{{1}}` = the person's first name** (T14). Today "Name" resolves to the lead TITLE, so customers get "Hi Bayut WhatsApp \| Md Sumon". Use NAME (first word) when it is a real name; otherwise the part of TITLE after the last `\|`. Reject phone numbers, "Missed Call…", "untitled" and empty values, and fall back to "there". `CampaignRecipient.name` must carry the same clean name, because the assistant greets with it. The deal path already strips the prefix (`a7_lead_wa.php:565`). Add cases to `campaigns/tests/test_crm_leads.py` | `ops/bitrix-aws/a7_lead_wa.php` (`a7_lead_wa_display`, :63-68, :264-269), `backend/apps/campaigns/crm_leads.py` (`detail_value`, `lead_display_name` :187-211; `renewals.py` imports it) | Open |
| C2 | **"Script" choice beside the Lead AI box** (T20b), shown only while the box is ticked: `General` / `International City shops`. Payload field `lead_ai_playbook` = `general` \| `ic_shops`; the PHP forwards it after checking it is one of the two; `campaigns/views.py` (:228, :282) passes it to `send_from_leads` / `send_renewals`, which call `mark_campaign(campaign, playbook=…)`. Deploy the Django part only after Claude's T20a is live | `ops/bitrix-aws/a7_lead_wa.js` (:766-786, :1385), `a7_lead_wa.php` (:1016), `a7_renewals_wa.js/.php`, `backend/apps/campaigns/views.py`, `crm_leads.py` (:348-404), `renewals.py` (:277-369) | Open |
| C3 | **Bitrix field map** (T50, Q10). Reuse: SOURCE_ID, Purpose `UF_CRM_LEAD_1737031634747` (for Broker), business activity, `UF_CRM_A7_AI_TRADE_LICENSE_STATUS` (add DED / Trakhees / New licence), Meeting Date & Time. Create on leads: **Shop Type Wanted** (Type 1 / Type 2 / Type 3 / Not sure), **Trade License File** (file), **Bot Status** (New / Qualifying / Viewing booked / Handed to agent / Broker / Lost / Opted out), **WhatsApp Opt-out** (Yes/No). Put them on the lead form. Write every UF id and enum id here under "Bitrix field map". Also list the STATUS_ID and stage-required fields of JUNK, Reject and "Not interested" (UC_RYQD1Z), so Matloob can pick the lost stage | Bitrix (`ops/bitrix-aws/`), this board | Open |
| C4 | **Field-only lead updates** (needed by T51). Check what BP 235 and the lead-shift timer do when a lead already in stage 10, or held by user 1, gets a `crm.lead.update` that changes fields only. If that plans another to-do or moves the lead, say how to avoid it. Write the answer here | Bitrix robots/BP, `a7_lead_shift.php` | Open |
| C5 | **Secrets out of the source** (low priority). `ops/bitrix-aws/a7_tl_phone_mask.config.php`: change the phone-mask password on the box, then `git rm --cached` the file and commit a `.example`. The 3CX tools (`a7_3cx_click_to_call*.php`, `a7_3cx_ai_recording_analyzer.php`) hard-code an OpenAI key, Bitrix webhook tokens and 3CX secrets: move them into an ignored config file. Both are already in `.gitignore` | `ops/bitrix-aws/` | Open |

### Bitrix field map (Cursor fills in, C3)

| Field | UF id | Enum ids |
|---|---|---|
| — | — | — |

## Requests (one side asking the other)

- Claude → Cursor: C1 and C2 touch `crm_leads.py` / `a7_lead_wa.*` (your 2026-10-12 work), so they are on your list. Claude will not edit those files.

## Known risks

- **Plaintext password in git:** `ops/bitrix-aws/a7_tl_phone_mask.config.php` is tracked with the phone-mask unlock password in plain text. It was already in the 2026-09-15 GitHub snapshot. Change the password and move the file out of git.
- **Broken probes:** 11 `ops/catalog` probes were deleted by another session, and their `ops/wa.sh` verbs now fail.
- **Shops script changes old rules:** it reverses several of the 2026-10-09 rules, so eval scenarios `shop-activity`, `shop-rent` and `shop-no-licence` must change with it.
