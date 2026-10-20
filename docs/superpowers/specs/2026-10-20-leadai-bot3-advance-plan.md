# Lead AI "Bot 3" — the advance plan (every community, live inventory, co-pilot, memory)

Written 2026-10-20 from Matloob's decisions of the same day, after the first mixed campaign (549–553) and gate round
12 (live 2026-10-19 18:50 UTC, main `94d21f7`). The issue list that fed this plan: `2026-10-19-leadai-campaign-1-issues.md`.
The 2e design this extends: `2026-10-16-leadai-2e-one-bot-design.md`.

## 0. Matloob's decisions (2026-10-20)

| # | Decision |
|---|----------|
| D1 | Target: **all communities**, not only International City. |
| D2 | Inventory: **Property Finder API now** (key given 2026-10-20, kept only in the server env — never in git, the board or TASKS); **Bayut / Dubizzle keys later**. **Bitrix Owner Data (Availability)** holds what the company has right now; Matloob provides Bitrix webhooks when asked. |
| D3 | Handover: **co-pilot** — the agent gets an AI draft and sends it, instead of the bot going silent. |
| D4 | Voice notes: customers may send as many as they like; all heard. |
| D5 | Quality first ("best"). |
| D6 | A **memory system**: the AI learns from how questions are asked and answered (chats, agents' answers, approvals). |
| D7 | The plan carries **Cursor's tasks** too. |
| D8 (M1) | The PF key has **every permission** already (Matloob, 2026-10-20 12:45). |
| D9 (M2) | The backend's **existing Bitrix CRM API key** is used for Owner Data too. |
| D10 (M3) | Owner Data → Availability (SPA 1042, category 14) stages mean what their names say: **Rent Availability** (205), **Sale Availability** (283), **Sale/Rent availability** (74) are the units available for that deal; **New Availability** (4,756) is the new, unverified pool; *contacted\details shared* (100), *future availability* (28), *No answer* (281), *Name* (28) are not stock to quote. Cards carry Community, Unit Type, No. of Bedroom, Size (sqft), Purpose, Lease Price, owner numbers — and many hold the details only in the **title** ("Tun Tun Naing, 240k, mudon 6, unit 190 and 187, 4br, g+1"), so the inventory service parses titles (price "240k"/"3.5M", community, bedrooms "3br"/"4br", "g+1") beside the fields. |
| D11 (M5) | The **meeting point is the office for every community**. |
| D12 (M4, M6, M7) | "Do what is best": knowledge proposals are approved by Matloob, TLs may propose; the co-pilot draft goes out by itself after 15 minutes for ordinary questions, never for price negotiation, legal matters or complaints; gpt-4.1-mini for turns, gpt-4.1 for drafts and proposals. |

## 1. Where we stand (facts, 2026-10-20)

**Live (round 12):** one bot for shops, studios and one-bedrooms in International City; rent, sale and shop tracks; the
real-model gate (574 runs, ≥95% and every strict scenario every run); office-visit and sales-call booking with slots,
reminders, full-name gate; opt-outs and PDPL deletion; handovers with alerts; the agent desk (needs-a-person rows,
"I'll call", today's visits/calls); unit photo sets; CRM mirror, Lead AI CRM fields, Bot Status; late answers (up to 20
hours); follow-ups (Template B, check-back, two nudges); **voice notes are already transcribed** (`assistant/transcribe.py`,
cached, on the lead's timeline). The 3 agents with Lead AI access: Hina Sultan, Mohammad Farhan, Shoaib Malik.

**Weak (campaign 1):** handover alerts answered 40–80 min late or never (42 escalations; I15); the same slot offer
repeated when two turns ran at once (I02); questions dodged (I09, fixed in code, but every new question type is a new
guard); static price bands and photo sets instead of real units; International City hard-wired (clusters, bands, shop
types, office); no memory across conversations (a new number = a new chat; a customer's July enquiry is unknown in
October unless the lead carries it); no learning loop — every mistake is found by hand in a chat review.

**Constraints that stay:** the gateway forwards text, media, template, interactive, location only (no read receipts,
no typing, no reactions); the 24-hour window opens only on an inbound message; MARKETING templates share Meta's
per-customer daily cap; the alots.io wallet can run dry (campaigns wait); BP 235 rewrites titles and wipes meeting
times on REST updates (Cursor's C26 skip in place); one conversation per (our number, customer).

## 2. Target architecture

```
 Property Finder API ─┐                               ┌─ Agent desk (co-pilot): drafts, send-as-me, ask-AI, SLA
 Bitrix Availability ─┼─► Inventory service ──► Engine ─┤
 (Owner Data, 1042)   │   (units, prices, photos)   ▲   └─ CRM: score, summary, stage, booking fields, timeline
 Bayut/Dubizzle later ┘                             │
                                                    │
 Community packs (facts per community) ─────────────┤
 Customer memory (per phone, across chats) ─────────┤
 Knowledge base (approved answers, FAQs) ───────────┘
                     ▲
 Learning loop: mined Q&A → approval screen → KB + replay scenarios → the gate
```

Everything the model is told stays **data** (customer words, listings, notes); code decides tracks, bookings,
opt-outs, figures and claims, as today. New sources are injected as blocks the prompt already has a shape for
(FACTS, LEAD CONTEXT), and every claim the model makes about a unit must be in the inventory block or it is cut
(`claims.py` grows an inventory check, like today's availability and figure guards).

## 3. Workstreams

### A. Foundation (before any scale-up) — Claude, ~4 days
| Item | Design | Proof |
|------|--------|-------|
| A1 I02 per-chat turn lock | Redis `SET NX` lease `leadai:turn:<conversation>` (TTL = turn budget) around `_claim`/`_run_claimed`; a second turn re-queues in 20 s instead of running beside the first. | Test: two claims at once → one runs, one requeues; live: no "two slot pairs in ten minutes" in the next campaign's review. |
| A2 Daily digest | Beat job 08:00 Dubai: replies / late / handovers waiting (and who took them) / bookings / opt-outs / model cost; to the panel (Lead AI → Reports) and a Bitrix IM to Matloob + the 3 agents. | The digest row exists for yesterday; numbers tie to the DB. |
| A3 Wallet guard | `gateway.credit` is read before a campaign is **queued** (not only before a follow-up): below N sends' worth, the queue is refused with the amount; an alert at 20% left. | Queue refused on a dry wallet in a test; alert row. |
| A4 Number quality watch | Meta quality rating per sending number (gateway/WABA endpoint if exposed; else the delivery-failure rate per number per hour); red/high-failure → that number pauses sends, alert. | A forced failure spike pauses the number in a test. |
| A5 Observability | `ops/wa.sh leadai-health`: sweep age, queue depth, turns/min, error rate, late answers; the digest uses it. | Verb output live. |

### B. Community packs — every community (D1) — Claude ~6 days, Cursor C43–C45
Today IC is in code: clusters (`tracks`, `_CLUSTER_WORDS`), bands (`residential_facts`), shop types, the office,
"Dragon Mart". A **community pack** replaces that:

- Model `LeadAiCommunity`: name, aliases (how customers write it: "IC", "international city", Urdu/Arabic), sub-areas
  (clusters/phases with aliases), unit types sold/rented there, **bands per unit type and deal** (fallback when
  inventory has no match), facts text (the FACTS block), meeting point (office or on-site, Maps link + pin), playbook
  knobs (shops yes/no, call-first for sales yes/no), languages, the photo sets per unit type.
- `tracks.decide` takes the community from the lead context (`FIELD_COMMUNITY`, `FIELD_CLUSTER` → pack + sub-area),
  from the campaign (its template's community), or from the customer's words (pack aliases) — code, never the model.
- The prompt's IC-specific wording becomes pack-driven lines (`residential.facts_block(pack)`); the shops flow stays an
  IC-only knob until another community sells shops.
- The eval gets a **scenario family per pack** generated from a table (ask price / cluster unknown / wrong community /
  "do you have anything in Mudon?"), so the gate covers every community without hand-written scenarios for each.
- Admin screen: Lead AI → Communities (list, edit facts, aliases, bands, meeting point, photo sets) — the panel, not
  Django admin, so Matloob edits it.
- **Cursor C43:** the Bitrix Community/Sub Community field map for every community (ids → names), as C38 did for IC.
  **C44:** campaign popups and bulk tools pick the community and pass `community` to the backend. **C45:** a Bitrix
  webhook (`ONCRMLEADUPDATE` or a field-only REST read) is not needed for this; the lead context read stays.

### C. Live inventory — Property Finder + Bitrix Availability (D2) — Claude ~8 days, Cursor C46–C48, Matloob M1–M3
What the bot quotes today is a band and a photo set. With inventory it quotes **the unit**: "a studio in England
Cluster, 420 sq ft, AED 31,000 a year, 2 cheques, vacant — photos below", and only units that exist.

- **Sources.** (1) Property Finder Enterprise API: the agency's own published listings (`GET /v1/listings` search;
  listing fields, prices, photos, links), and `GET /v1/leads` + `/v1/webhooks` for PF leads if the scopes allow
  (the API doc is password-protected; the key's scopes decide — see M1). (2) Bitrix **Owner Data → Availability**
  (SPA 1042, the New Availability stage: 4,741 cards on 2026-10-19): what the company has, published or not, with the
  owner's price and the responsible agent. (3) Bayut/Dubizzle later, same shape.
- **Service** `apps/inventory`: `Unit` rows (source, source_id, community, sub-area, unit type, bedrooms, size, price,
  cheques, furnished, vacant/tenanted, photos, link, responsible, updated_at, active), refreshed by a beat job (PF every
  30 min; Bitrix on its webhook, else every 15 min). Matching rules: PF ref ↔ Bitrix "a7group-NNNN" ref, else
  (community, sub-area, type, size ±5%, price ±3%). One truth per unit: Bitrix availability + owner price win on
  "is it available / at what price"; PF wins on photos and the public link.
- **In the turn:** the engine asks the service for the customer's need (community, sub-area, type, budget, vacant)
  → up to 3 units as an INVENTORY block (data); code cuts any unit claim not in the block (`claims.inventory`); the
  photo step sends the matched unit's photos (unit_media gains a "from inventory" set); a booking records the unit on
  the appointment and in the CRM (a Property link in the lead/deal).
- **Fallback:** no match → today's band + photo set, and the model says "options in that range" — never a made-up unit.
- **Gate:** scenario family "inventory": price asked with a match → the unit's price; with no match → the band; a unit
  the inventory lacks is never named; vacant/tenanted answered from the unit.
- **Cursor C46:** a Bitrix outgoing webhook on Availability item add/update/stage change → `POST /api/inventory/bitrix/`
  (signed), with the field map of the Availability card (price, type, community, sub-community, size, status,
  responsible, photos). **C47:** the Availability card gets "Published on PF: ref/link" so agents see the match.
  **C48:** a "Units sent" timeline note per chat (which units the bot showed).
- **Matloob M1:** PF key scopes (listings:read at least; leads:read and webhooks if we want PF leads straight into
  the bot) — confirm in the PF Manager → Integrations; the key is for the inventory feature only (`LEADAI_PF_API_KEY`,
  `LEADAI_PF_API_SECRET` in the backend env; rotate the one pasted in chat once this is live). **M2:** the Bitrix
  incoming webhook with `crm` scope for SPA 1042 reads (if the existing one lacks it). **M3:** which Availability
  stages count as "available".

### D. Co-pilot desk (D3) — Claude ~6 days, Cursor C49
Today a handover makes the bot silent until a person writes, and alerts went unanswered for 40–80 minutes.

- **Draft on handover.** When a chat needs a person (handover, broker, must-answer question, booking question the
  rules refuse), the engine produces a **draft reply** (model + the same guards, marked `draft`) and the desk shows it
  under the chat: *Send as me* (goes out from the chat's number, logged as the agent's), *Edit & send*, *Ask AI*
  (the agent types a question, gets a draft), *Let the bot continue* (resume). The customer never sees a draft.
- **SLA timer.** Each needs-a-person row shows minutes waiting; at 10 min an escalation IM to the lead's responsible
  and their TL (Cursor C49 gives the TL map); at 30 min to Matloob. The digest reports median time-to-first-human.
- **Learning capture.** Every edited-and-sent draft is stored as (customer words, draft, agent's final text) — the
  raw material of the knowledge base (E).
- **Gate:** draft quality is judged by the eval like a reply (words=MODEL), on handover scenarios: a draft exists,
  carries no figure outside the facts, no colleague's name, no promise of a call that nobody booked.
- **Cursor C49:** a Bitrix user → TL/department map endpoint (or a UF on the user), read by the escalation.

### E. Memory and learning (D6) — Claude ~9 days, Matloob M4
Three layers, all **data in the prompt**, never instructions:

1. **Customer memory (per phone, across conversations and numbers).** `LeadAiCustomer` keyed by the phone: needs
   and facts the chats learned (unit, community, budget, for whom, move-in), bookings and their outcomes, opt-out
   state, language, the last chats' one-line summaries. Written by the turn's `_apply` and the booking/visit events;
   read at the first turn of any new conversation with that phone ("you asked about a studio in Spain Cluster in
   July — still that?" becomes possible, as a question, never a statement: I12's rule). PDPL deletion wipes it.
2. **Knowledge base (the company's answers).** `LeadAiKnowledge` rows: question pattern (as customers ask it, in
   their words and languages), approved answer (English + the languages it was approved in), community/pack scope,
   source (agent's edited draft, Matloob's entry, a chat review finding), status (proposed / approved / retired),
   hits. Retrieval: OpenAI embeddings on the question side + pgvector (Postgres) — top 3 approved entries for the
   customer's burst go into a KNOWLEDGE block; the model must answer from it when it matches, and `claims` cuts a
   figure or a fact that is neither in FACTS, INVENTORY nor KNOWLEDGE.
3. **Learning loop.** A weekly job mines the chats: questions the bot handed over or dodged, answers agents gave
   (co-pilot edits), review findings → **proposals** on a panel screen (Lead AI → Knowledge): Matloob or a TL approves,
   edits or rejects (M4: who approves). Approved entries also become **replay scenarios** (the customer's real words,
   the approved answer's must-haves) appended to the eval, so the gate proves the bot now answers them — this is how
   "the AI is trained": not by fine-tuning, which would bake in mistakes and cost a gate per retrain, but by an
   approved, testable knowledge base plus the gate. Fine-tuning gpt-4.1-mini on approved pairs is a later option once
   the KB has 500+ entries and the replay suite is stable.
- **Gate:** scenario family "knowledge": a KB-answered question gets the approved answer's facts; a KB entry out of
  scope (another community) is not used; a retired entry is not used.

### F. Sales flow: score, post-viewing, booking, cadence — Claude ~7 days, Cursor C50–C53
- **F1 Lead score** (hot/warm/cold + reasons) computed by code from the chat's facts and events (budget known, unit
  named, visit booked/attended, replies within an hour, decline words) — not by the model alone; written to a Bitrix
  field (`UF_CRM_A7_AI_SCORE`, Cursor C50) and shown on the desk, which sorts hot first.
- **F2 Post-viewing.** 2 hours after a booked visit's start (and the agent did not mark it missed): "How was the
  visit? Shall we move ahead with <unit>?" → yes → Bot Status "Booking requested", alert to the responsible, CRM stage
  Meeting Done; no → the reason (price / location / size) into facts and the lost reason; silence → one nudge next
  morning. Cursor C51: the stage moves without BP 235 side effects (as C26).
- **F3 Booking automation.** When the lead reaches Booking (or the agent marks "booking requested"): the bot sends the
  documents checklist for the unit's deal type (rent: Emirates ID/passport + visa, cheques; sale: passport, proof of
  funds), collects the documents (the licence-copy flow generalised: `documents.py`), confirms receipt, and writes
  them on the lead (Cursor C52: the document fields and the booking fields filled from the bot: Rent or Sale and
  Commission Zone from the unit; the rest stays the agents').
- **F4 Cadence.** Beyond Template B and the nudges: day 3 / 7 / 30 re-engagement templates per pack (new units in your
  budget, price change, "still looking?"), one per customer per window, held by every rule followups.py holds today
  (declines, not now, opt-out, handover). Cursor C53: the templates submitted on the 8 WABAs.
- **F5 Referral.** After a deal's Booking → Paid (Commission Status Paid), one message a week later: "know someone
  looking?" with the number to share; never twice.

### G. Voice and media (D4) — Claude ~3 days
- Voice: already heard. Improve: notes over 2 minutes (chunked), several notes in one burst (one transcript, in order),
  a Urdu/Hindi/Arabic language hint from the chat's language to Whisper, a "could not hear" line in the customer's
  language with a request to type, and the eval family "voice" (the transcript stands in for the text).
- Images: a listing screenshot or a photo of a building the customer sends → a vision read (what listing / which
  cluster / which price is in the picture) as data; the bot answers about *that* unit when the inventory finds it.
- Documents (PDF/images) the booking flow asks for: F3.

### H. Reporting — Claude ~3 days, Cursor C54
- Panel: Lead AI → Reports: the funnel per campaign and per community (sent → delivered → replied → qualified → booked
  → visited → booking → paid), time-to-first-human, model cost per booking, numbers' health; CSV export.
- Cursor C54: the same funnel as a Bitrix report (the weekly funnel definitions of C30).

## 4. Cursor's list (C43–C54), in one place
| # | Task | Needed for |
|---|------|-----------|
| C43 | Community / Sub Community field map for every community (ids → names, aliases), as C38 did for IC | B |
| C44 | Campaign popups and bulk tools: pick the community, pass `community` to the backend; template per community | B, F4 |
| C45 | Nothing — the lead context read covers it (listed so nobody builds a webhook for it) | B |
| C46 | Bitrix outgoing webhook on Availability (SPA 1042) add/update/stage → `POST /api/inventory/bitrix/` (signed), field map of the card | C |
| C47 | Availability card: "Published on PF: ref/link" from the backend's match | C |
| C48 | "Units sent" timeline note per chat | C |
| C49 | User → TL/department map (endpoint or UF) for escalation | D |
| C50 | `UF_CRM_A7_AI_SCORE` (+ reasons text) on leads; kanban column | F1 |
| C51 | Stage moves Meeting Done / Booking requested without BP 235 side effects (as C26) | F2 |
| C52 | Document fields on the lead (Emirates ID, passport, visa, proof of funds), the booking fields filled from the bot (Rent or Sale, Commission Zone) | F3 |
| C53 | Re-engagement templates (day 3/7/30, per community) submitted on the 8 WABAs | F4 |
| C54 | Funnel as a Bitrix report (C30 definitions) | H |

## 5. Matloob's list (M1–M7)
| # | Ask |
|---|-----|
| M1 | Property Finder: confirm the key's scopes in PF Manager → Integrations (listings read at least; leads + webhooks if PF leads should reach the bot directly). The key lives in the server env only; rotate it after go-live since it was pasted in chat. |
| M2 | Bitrix incoming webhook with `crm` scope for SPA 1042 (Owner Data/Availability) reads, if the one the backend has lacks it. |
| M3 | Which Availability stages mean "available" (New Availability? others?), and whether owner price or marketed price is quoted. |
| M4 | Who approves knowledge-base proposals: you only, or the TLs too? |
| M5 | The list of communities to launch first (we have IC; next: Damac Lagoons? Mudon? Villanova? Dubai South?) and each one's meeting point (office or on-site). |
| M6 | Co-pilot: if no agent sends within N minutes, should the bot send its own draft? (my suggestion: yes after 15 min for ordinary questions, never for price negotiation, legal, complaints) |
| M7 | Model budget: gpt-4.1-mini stays for turns; gpt-4.1 for co-pilot drafts and KB proposals (~3× the price per call, small volume) — OK? |

## 6. Sequence (weeks), gates and rollout
1. **Week 1:** A (foundation) + G1 (voice polish) → gate round → live. B's model + admin screen started.
2. **Week 2–3:** B (community packs) with the scenario families; M5's first two communities on test numbers → one
   small campaign per community → review like campaign 1 → live.
3. **Week 3–4:** C (inventory: PF read + Bitrix Availability webhook) behind a kill switch (`INVENTORY_LIVE`); IC
   first, then every pack.
4. **Week 4–5:** D (co-pilot) + E1 (customer memory) → the agents try it on the desk for a week.
5. **Week 5–7:** E2–E3 (knowledge base + learning loop + replay suite), F1–F2.
6. **Week 7–9:** F3–F5, H, G2.
Every step: the real-model gate (≥95%, every strict scenario every run, the new scenario family included), Postgres
tests on the image, `up app` with all four services, a probe, a TASKS entry with what was proven and what was not.
Each feature ships behind its own switch in `LeadAiSettings`, so a bad day turns one thing off, not the bot.

## 6a. What the data showed on day 1 (2026-10-20, read-only probes)
- **Property Finder** (atlas.propertyfinder.com Enterprise API; the key has every scope: listings, leads, webhooks, users):
  142 live listings — 48 townhouses, 34 shops, 33 villas, 24 apartments; **International City holds 5** (4 shops, one
  townhouse in Warsan Village). The token lasts 30 minutes; listings page by 50 (`filter[state]=live`); a listing gives a
  location id only, so the community and cluster are read from its title. 10,000 leads, and webhooks `lead.created` /
  `lead.updated` already point at a youtupia.com endpoint (whoever built the PF → Bitrix lead feed).
- **Bitrix Owner Data → Availability** (SPA 1042, category 14; user fields `UF_CRM_5_*`): the three "available" stages
  hold 562 cards — of those, **145 carry no bedrooms, unit type or purpose at all**, most of the rest carry one or two,
  and the price and the place sit in the title ("Maitha , 230k , unit 292 , mudon 6 , 3br , g+1") or nowhere. No Community
  field exists on the card (the kanban's "Community" is another field's label). The enum lists are polluted with phone
  numbers and prices typed as options.
- **So:** the inventory v1 quotes only clean, matched units (`LeadAiUnit`, synced every half hour from both sources);
  International City studios and one-bedrooms — the campaigns' own subject — fall back to the bands until the Availability
  data is cleaned. **Cursor C55:** a validation on the Availability card (bedrooms, unit type, purpose, price, community
  required before a card may enter Rent/Sale Availability) and a bulk title parser for the existing cards — without it the
  live inventory stays thin for the units the campaigns sell.

## 6b. Day 2 of the fast track (2026-10-20): what shipped, what was cut
- **A2 daily digest** — `assistant/digest.py`, `LeadAiDigest` (migration 0014): the Dubai day's replies, skipped and failed
  turns, late answers (over a minute), handovers with who took them and how fast (from `LeadAiTurn.actions.handover` and
  the first message of ours after it that is not the assistant's), the co-pilot's draft outcomes, bookings, opt-outs, the
  stale alerts and the model's cost (tokens × list price by model name). The minute sweep stores yesterday's from 08:00
  Dubai and sends it once to the panel admins and the Lead AI alert list; a day the sweep missed is stored on a later sweep
  without a bell (up to seven back). Panel: Lead AI → **Reports** (today so far, the last digest, one row per day).
- **A5 observability** — `ops/wa.sh leadai-health` (management command `leadai_health`): the switch, the sweep's age, the
  leadai queue's depth, the last hour's turns and latency, stuck turns, chats waiting for a person, drafts waiting, stale
  alerts, the inventory's age, the keys, the last digest, today so far; exit 1 when something is red.
- **C, location names** — a Property Finder listing's location id is read once per id (`GET /v1/locations?filter[id]=`): the
  tree names the community and the sub-community a title does not (72 of 142 live listings had no community on day 1).
- **B, v1 = the data layer** — `LeadAiCommunity` (seeded: International City with its clusters and the 12 other communities
  the agency lists, aliases only, no band), `assistant/communities.py` deciding the chat's pack by code (stored → lead
  context → the customer's words → the default), stored on `LeadAiChatState.community`, shown to the panel
  (`lead_ai_ai.community`), read by the inventory match. **Not yet (B2–B4):** the flow per community. A home outside
  International City still goes to the OTHER track (`tracks.other_area`, the "many options across Dubai" line), villas and
  townhouses too; a pack's bands, facts and meeting point reach the prompt only once that flow exists. Needs Matloob's word
  on what the bot says for a Villanova townhouse or a Mudon villa (quote the Property Finder unit? call first?).
- **A3 wallet guard — cut by Matloob (2026-10-20): "credits wala part skip kar do, main khud dekh loon ga."**
- **Round 15's gate** (first run of the day) failed on one test and two strict scenarios: the general prompt's byte-for-byte
  hash (round 15 changed the general prompt on purpose: recorded), `shops-res-for-myself` (the cluster question before the
  balcony and move-in question: `residential.requirement_first`) and `shops-nine-questions-noted-95` (a numbered question
  of theirs lost: `crm_facts._numbered_questions`). Round 16 carries rounds 15 and 16 together.

## 6c. Round 17 (2026-10-20, afternoon): the community packs' flow, v1
Matloob's word on B2: for a home outside International City the bot quotes the Property Finder unit, sends its photos
and refers the customer to our office ("pictures wagera PF se jayein aur office refer karein").
- **Decision (code):** `tracks.pack_decision` — a home named with a community that has a pack *and live units*
  (`communities.named_packs`) takes that pack's rent or sale track with the unit as named (villa, townhouse, two
  bedrooms or more, studio, one-bedroom); the community travels on the `Decision` and is stored on the state. A
  community with nothing listed stays another area (OTHER) exactly as before, so the gate's IC scenarios are untouched.
- **Prompt:** `PACK_SYSTEM` — RES_SYSTEM's shared sections word for word; its own head, TRACK, HARD RULES (prices from
  INVENTORY only, the system sends the photos, every visit starts at our office), STEPS and CHARGES. Cached apart.
- **Context:** the pack's facts in RES FACTS' place (`communities.facts_block`), COMMUNITY lines, INVENTORY for that
  community (two bedrooms or more match villas and townhouses too: `inventory.pack_units`), no IC charge lines.
- **Guards:** no opener of code's; International City's steps off; "we have …" kept for listed units; the price asked
  with no figure in the reply gets the listed unit's own line (`residential.pack_quote`); nothing listed → the honest
  six-language line (`res_pack_no_units`); the amount filter still cuts any figure INVENTORY lacks.
- **Photos:** `pack_photos.send_photos` — the quoted unit's first three Property Finder photos, kept as inbox
  attachments, uploaded to the gateway for the chat's number and sent once per unit per chat, from their own task.
- **Seed:** Cursor's C43 spellings became packs (migration 0015 adds the rows and the aliases).
- **Not yet:** the sale flow's call-first for packs (Matloob chose the office visit for both), pack bands edited in the
  panel (Django admin today), the desk showing the community, a scenario family per pack beyond the three scenarios.

## 7. Risks
- PF API scopes may be listings-write only (publishing), not read: then the inventory reads Bitrix Availability alone
  and PF photos come from the listing link (M1 decides on day 1).
- Inventory freshness: a unit rented an hour ago is still "available" until the next refresh — the booking confirms
  availability with the responsible agent (the alert), never promises it.
- Memory across numbers must respect opt-outs and PDPL deletion (one wipe clears memory, KB sources from that
  customer, transcripts).
- Co-pilot drafts sent "as me" are the agent's words: logged with the agent's id; the digest shows who sent what.
- Model cost rises with inventory/knowledge blocks (longer prompts): prompt caching keeps the fixed blocks cheap;
  the digest shows cost per booking.

## 8. Not in this plan
Fine-tuning (later, see E3), a customer-facing web app, telephony, a bot for owners/landlords (a separate plan).
