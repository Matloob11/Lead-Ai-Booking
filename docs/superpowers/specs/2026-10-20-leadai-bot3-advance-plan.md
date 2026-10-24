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

## 6d. Rounds 18–20 (2026-10-21): the packs edited in the panel, the campaign's community, Cursor's ids consumed
- **Round 18:** `residential.segment_of` gives the model's unknown segment a residential track (the customer's own time
  gets booked; shops-mixed-not-known-booking had failed 1/2 for three rounds); the Property Finder sync counts a
  listing repeated across overlapping pages once and stops an endless nextPage (40 pages); `probe-leadai-turn` books a
  free hour instead of a fixed 5 pm; the thread shows the community chip. 18b: the hourly reason read from the English
  gloss too (`passed_over_hour`), a buyer abroad read from their own words (`sales.abroad_words`).
- **Round 19 (B2's editor):** the Communities dialog on the Lead AI screen — aliases, sub-areas, units, bands, facts,
  meeting point, maps link, shops, on/off — read by everyone, saved by a panel admin (`PUT /api/leadai/communities/<id>/`,
  `POST …/new/`, `communities.validate`). `LeadAiCampaign.community` (migration 0016): `lane.mark_campaign(community=)`
  for Cursor's C44b; a chat reads its campaign's community until its own words name another.
- **Round 20 (C's Bitrix half, D's escalation):** the Availability card's own Community name (C59, enum 2526–2579 →
  the bot's spellings; an International City cluster names the cluster) and Property Finder ref (C62) read into the
  inventory; a card published on Property Finder counts once (the listing, with its photos, stands for both).
  `POST /api/leadai/inventory/bitrix/` (C46, signed "leadai-inventory.") reads the one card again in a task
  (`inventory.refresh_bitrix`); Cursor enables the handler after "round 20 is live". A handover nobody answered in 30
  minutes reaches the responsible's team lead and department head too (`escalation.above`, C49's map, cached six
  hours; `LEADAI_BITRIX_ESCALATION_URL`, empty = off).
- **Round 20b (the review before the gate):** three adversarial readers over the round's diff (correctness, contract,
  integration) and a refuter per finding confirmed seven defects, all absorbed in code: alias-only community names
  stored under the pack's name (`inventory.pack_names`), the sync's retire sparing a webhook-refreshed row, a refusal
  that is not "not found" leaving a card's units, the Property Finder twin dropped per (reference, deal) before any
  cut, a hold-user responsible asking for the owner's people, a nested body 400 not 500 with nothing unsigned parsed,
  one card read per half minute, the whole escalation map in one call and the sweep running escalation last.
- **Round 20c (the gate's own failure):** shops-res-for-myself failed one run — the cluster question plus "a preferred
  move-in date?", no balcony — and `residential.requirement_first` now stands aside only when both halves of step 2's
  first half are asked; the cluster, or one half alone, gets code's balcony and move-in question. The second gate failed
  one run of shops-res-invitation-two-slots ("Just me" answered with a contract question, no invitation): on the rent
  track, our who-will-stay question answered with themselves alone and no invitation in the reply now gets code's
  invitation with two free slots (`engine.alone_invitation`). The third gate failed one run of shops-res-cluster-unknown
  (the move-in asked again in more detail, no cluster): our balcony and move-in question answered (a fact or their words,
  `residential.requirement_answered`) now drops a repeat of it and code's cluster question goes.
- **Waits:** the 10-minute first escalation step of D stays at 30 minutes for every recipient.

## 6e. Round 21 (2026-10-21): the lead score, F1
- **The score (`assistant/score.py`):** 0–100 from the chat's facts and events — they wrote, the unit, the deal, the
  budget, the area, the move-in, a full name, a visit or call booked / done / held / cancelled, how fast they answer,
  the model's "wants to move fast", abroad, and the quiet (3 days −10, 7 days −20); a STOP or a no is 0, a broker 5.
  Hot from 70, warm from 40; the reasons in English ("Hot 85: they wrote; unit known; …").
- **Where:** `LeadAiChatState.score / score_reasons / scored_at` (migration 0017), set at the end of every shops turn
  and once a day for quiet chats (`rescore_quiet` after the digest); the lead's `UF_CRM_A7_AI_SCORE` and `_WHY`
  written through the fields tool when the value moved (Cursor's C50, allowed since C65).
- **The desk:** the chip on every row and thread, a Hot first sort (`?sort=score`, the unscored last).
- **Not yet:** the digest's time-to-first-human by score band; a backfill of the chats that never speak again.

## 6f. Round 22 (2026-10-21): the new-lead greet (Bot 1's first half)
Matloob's ask: new leads get the AI too — the listing they came from, its details, anything else they want, the slots,
the viewing. Campaign-first, so the 24-hour window never blocks the first message.
- **Trigger:** Cursor's C67 handler on lead creation → `POST /api/leadai/bitrix/new-lead/` (signed like C46) → a
  minute later `tasks.greet_new_lead` → `newlead.greet`.
- **Greet:** the lead read; skipped unless New, fresh (48 h), with a phone, not opted out / broker / Lost, not in a
  Lead AI chat, never reached by a Lead AI campaign; then the greet template through the popup's own path
  (`send_from_leads`: a one-recipient Lead AI campaign, ic_shops, the community from the lead); `{{2}}` the listing
  in words. Settings in Django admin (`greet_*`, migration 0018).
- **The listing:** the comment's Listing ID / a7group ref / Bayut link into the lead context; `inventory.enquired`
  puts that unit first in the first turn's INVENTORY block, marked, "no longer listed" when it went.
- **The review before the gate (22b):** a portal's lead only (the inbox's "Create lead" for a chat in progress would
  have pulled the agent's chat onto the Lead AI screen), a customer talking to us already or greeted within 24 hours
  left alone, the settings a send would refuse named as skips, a villa named a villa, a retired enquired listing kept
  from code's guards and the photos.
- **22d (2026-10-22, the first live greets):** a lead with no Community field takes the enquired listing's community
  for its chat (the first greet left a Serena townhouse's chat with none).
- **22e (2026-10-22, the first real reply):** chat 52745, a Bayut studio lead asking for the payment plan, got the shop
  types list: `ic_templates.kind` read the greet template as a shops one, so `tracks.decide` never let the lead context
  decide (step 4 is the mixed template's) and chose the shop track by the template. The greet template is now its own
  kind (`ic_templates.PORTAL`, any template named `portal_…`), answered for by the lead context first as the mixed
  template is; `lead_context.enrich` fills a lead that names only a listing from the inventory (unit, property, deal,
  community, cluster; stored by `keep`, used by the greet); a pack lead's yes is the model's turn (`tracks.first_yes`),
  never "a shop, a studio or a one-bedroom"; `newlead.template_ready` refuses a greet template of another kind; seven
  `shops-portal-*` eval scenarios. The greet was off from 06:10 UTC until 22e went live.
- **Not yet:** the client-first half (the customer writes first to the ad's number: T80/T81), a "closer" prompt (T82),
  the enquired unit's photos on the first turn outside the pack flow, the rest of an eval family for portal leads (a
  reply in Arabic or Urdu, a voice note, a reply after 24 hours, a listing gone).

## 6g. Round 22f (2026-10-22): the "AI auto reply" label and "reconnect again"

- **The label:** every chat a new-lead greet campaign made carries the inbox label "AI auto reply"
  (`newlead.label_greeted`, from the sweep), so an agent tells an automatic reply's chat from a campaign's.
- **Reconnect again (`reconnect.py`, `leadai_reconnect_again`):** one more template to the mixed campaign's
  customers who never said no, so the assistant can talk to them. Per recipient: *in the chat* (the campaign reached
  them; nothing says no per `followups.blocked`; no viewing open; quiet 48 h; the number not dead; not sent already)
  the template `intl_city_property_reconnect_again` (MARKETING, `{{1}}` the first name, the mixed template's quick
  replies; `ic_templates.kind` MIXED) inside the same chat, as Template B goes; *fresh* (never messaged: the cap
  skipped them) a Lead AI campaign per original number through the popup's path and rules; *out* with the reason. A
  dry run unless `--send`; Template B's hours. The 19 October campaign's facts that shaped it: 1,295 leads, 781
  reached, 246 replied, 412 never messaged for Meta's marketing daily cap, 102 failed.

## 6h. Round 23 (2026-10-22): the handover desk ("My handovers")

- **Matloob's order:** when the AI hands a chat to a person (a human or a call asked for, a complaint, legal, a broker,
  a person's Bot Status in Bitrix), the lead's Bitrix Responsible sees that chat, and only their handed-over chats, on
  their own screen: the chat and the customer, their own chat's viewing, nothing else of the panel (no other chats, no
  numbers, no counts, no meetings list). They reply there, send a template from the chat's own number, press Done. The
  assistant keeps its ways (quiet while handed over, the co-pilot draft, back in full once a person wrote); admins keep
  everything. Access needs no grant: every agent has a Bitrix id.
- **Backend (`apps/leadai/handover_desk.py`, migration 0019):** `LeadAiChatState.desk_at` / `desk_reason` /
  `desk_done_at` / `desk_done_by`, the durable marker (`handed_over_at` clears the moment a person writes), set by `mark`
  from `engine._apply` at every handover and broker and from `bitrix_status.apply` for a person's Handed/Broker; cleared
  by Done (`POST /api/leadai/chats/<id>/desk/done/`: it ends an open handover and the handover's own pause, Bitrix's
  Handed to agent, so the assistant answers in full again; an agent's own Pause stays, and a broker's) and by Move to
  inbox; the migration puts the chats handed over before it (59 live, the oldest from the 15th) on their desks. **Who:**
  `responsible_bitrix_user_id == the agent's bitrix_user_id` at query time (Bitrix users 0 and 1, who hold unassigned
  leads, have no desk), read again every hour while on a desk (`refresh_responsibles`) and at every handover.
  **Visibility:** one clause, `mine_q`, OR-ed into `inbox.visibility.visible_conversation_q`, so every inbox and Lead AI
  endpoint follows unchanged. **List:** `GET /api/leadai/desk/mine/` (`?agent=` for an admin), rows trimmed to the chat
  and the customer, "they wrote" one `Exists` for the whole list. An agent who has a chat through the desk alone
  (`only_through_desk`: no admin, no Lead AI access, not the owner, none of the number's holders) gets the chat detail
  the list's rows and the live frames trimmed the same way (`trim`, `trim_live`; `lane.desk_groups_for`), and
  `leadai.desk.changed` tells their screen a chat came onto, or left, their desk (Done, a move, a Bitrix
  reassignment), with their count. A responsible who is no admin, has no Lead AI access and does not own the chat
  hears nothing of it otherwise (an agent joins no number group), so their own channel gets the chat's frames: in full
  when they hold its number, trimmed when they have the chat through the desk alone. A re-read of the lead's Bot
  Status before a nudge (`followups.bitrix_blocks`) applies no Handed to agent again after Done
  (`bitrix_status.apply(reread=True)` while `desk_done_at` stands); a person's fresh change still does.
- **Panel:** `modules/lead-ai/handovers.js` ("My handovers": the hamburger menu item with the count, the no-number
  card's door, a live socket of its own for an agent with no number), `thread.js` in scoped mode (Done; no AI controls,
  no Move to inbox, no line on the owner, the campaign, the CRM record or the memory; our number as digits only),
  `lead-ai.js` (an agent with no admin rights, no Lead AI access and no number opens every Lead AI door on this screen;
  the badge follows `leadai.desk.changed`; no chime for the chat open on the desk), `lead-ai.css` (two columns).
- **The gate's two eval guards (the same day, the deployed gate's eval):** a complaint the model apologised for without
  the handover is `complaint_or_upset` (`engine.complaint_handover`; eval `complaint`, both runs); "I will reach by 5:30"
  after the Running Late tap, read by the model as a reschedule to 17:30, is their late arrival
  (`engine.late_arrival`; eval `booked-running-late`, one run of two). Tests: `tests/test_r23_guards.py`.
- **Not yet:** in `apps/inbox/views.py` (Cursor's uncommitted copy is what the server holds, so it was left alone) the
  messages endpoint's embedded chat still carries the owner's name and the number's title to a scoped agent, which the
  panel hides, and `contact_detail` gives them the owner's Bitrix id, the number roster and the assignment history;
  Resume AI on a Bitrix-handed chat has the re-read hole Done had; a handover's Bitrix notification still says "until
  someone from the team writes".

## 6i. Round 25 (2026-10-23): "Lead AI access" per Bitrix user (All chats / Today / Needs a person)

- **Matloob's order:** an access management screen, agent by agent: if someone should see the Today bookings, or
  whatever we choose, we manage it there, connected to Bitrix in real time.
- **Backend (`apps/leadai/access.py`, migration 0021 `LeadAiAccess`):** three grants keyed by the **Bitrix user id**
  (as the handover desk is, so a grant made before the person ever signed in holds from their first sign-in):
  **All chats** (every active Lead AI chat on any number, its live group and its alerts; the same grant Agents & access
  calls Lead AI access, `Agent.can_lead_ai`, kept in step both ways: `access.grant` writes the account's flag, the
  Agents & access change calls `access.sync_from_agent`), **Today** (the chats with an open visit or call of the day,
  Dubai time, `desk.today_window`), **Needs a person** (the chats handed over or broker-paused and not stopped, or with
  an open tentative). `access.of(user)` is the effective dict, read once per request; a panel admin has everything, an
  inactive account or one without the Official API inbox nothing. `access.q_for(user)` is one clause OR-ed into every
  agent's visibility through `lane.desk_q`, so every inbox and Lead AI endpoint follows unchanged, and an agent with
  no grant keeps exactly what they had (their own chats, "My handovers"); the Today and Needs a person lists are views
  of the visible chats. `lane.has_desk_access` reads the row too; `alerts.desk_agents` both the flag and the rows.
  `GET /api/leadai/access/` (admins) merges the portal's active users (`user.get` through the webhook, the `user`
  scope; paged by 50, cached a minute, `?refresh=1`) with the panel's accounts by Bitrix id (the hold users 0 and 1
  left out), each with the handovers on their desk; `PUT /api/leadai/access/<bitrix id>/` sets one or more flags
  (never a hold user, never one's own id), records who and when in the row's history, and publishes
  `leadai.access.changed` to the agent's own channel: their open socket reads its groups again from the row as it is
  now (`inbox.consumers._rejoin`), their panel reads its lists again. `/api/auth/me/` carries `lead_ai_access`.
- **A granted agent's chats:** in full, as the team sees them (`handover_desk.Scope`: nothing trimmed as for a
  responsible through the desk alone), with their live frames on the agent's own channel (`access.event_groups`
  through `lane.desk_groups_for`: the agents whose Today or Needs a person grant covers the chat); the open
  socket reads its groups again on `leadai.access.changed` (`inbox.consumers._rejoin`); a chat of the Lead AI desk
  that is not in their lists reaches them as an id-only `leadai.access.resync` (`access.ping_groups`, through
  `inbox.events.publish_resync`; never for a receipt, "the AI is writing" or a reaction, which move no chat between
  lists; from Move to inbox to the desk's group too), so a chat that just left a list goes from their screen (the
  panel lets the row go as for a chat moved back to the inbox; the open chat's note says so in those words until
  screen.js carries a note of its own). A stopped chat with a tentative is no Needs chat. A chat on someone's handover
  desk counts as waiting for a person until Done (`needs_q`: `desk_at` set, `desk_done_at` not), so the chat a
  granted agent answered stays with them while the assistant takes over again; their New template writes for their
  chats' accounts (`catalog._covered_waba_ids`). The migration backfills a
  row for every account granted Lead AI access in Agents & access before, so the screen can revoke it (a revoke
  clears the row and the flag); a grant made before the account exists reaches the account's own flag the first
  time it is seen (`access.of`). "Admin" on the screen is a panel admin (`sees_all_inbox_chats`), as the
  endpoints mean it: a Bitrix portal admin who is no panel admin gets switches like anyone.
- **Panel (`modules/lead-ai/access.js`, new; `lead-ai.js`, `access-requests.js`):** the hamburger menu's "Lead AI access" (panel admins):
  name and position from the portal, the account's state (signed in when, never, inactive, no account yet), the
  handovers, three switches (an admin's locked as everything, one's own locked, an unusable account's locked), a
  search, "Refresh from Bitrix"; each switch one PUT (the row's three switches held while it is in flight), the row
  replaced by the server's answer. An agent granted the Today or the Needs a person list opens the Lead AI screen
  (not the handover desk's), from the menu and from the no-number card's door, and sees the chats of their grant.
- **Not touched:** `screen.js`, `thread.js`, `lead-ai.css`, `api.js`, `inbox.js`, `index.html` (another session's
  uncommitted copies are what the server holds); so the screen's rail is not yet shaped by the grant: every tab
  lists the visible chats, which for a Today or Needs a person grant are those chats alone.

## 6j. Round 26 (2026-10-23): the AI does not give up on a first "no" (the other-areas offer)

- **Matloob's order (from chat 54622 / lead 73988, the reconnect campaign):** "No I'm good thanks / We are not looking
  for properties in that area anymore" got "No problem, thank you for letting us know." and the lead went Lost. The AI
  must not give up: it says we can show other areas too, wherever they say, and asks where they are looking.
- **The rule (`engine.offers_other_areas`, `other_areas_offer`; `rules.LINES["other_areas"]`, six languages):** a first
  "not interested" gets, in place of the close, "No problem. We also have options in other areas of Dubai, for example
  X, Y and Z. Which area are you looking in, and what kind of unit? We can show you there." (up to three other
  communities with a live unit, `communities.named_packs`; none named when none). The chat stays open, nothing is Lost,
  `facts.other_areas_offered` remembers it (written only once the line went); a second no closes as before. In both
  sinks: `_opt_out` (the model's tag, or settle's) and `_rule_opt_out` (code's whole-message "No thanks", before any
  model). Never for a STOP or a wrong number, a tap that is the opt-out anywhere in the burst, a shops rule (the
  check-back's No, the second-shop No), a pending check-back, a place found elsewhere (`place_found`: `_HAS_PLACE` with
  the Roman Urdu, Urdu and Hindi forms, `needs.rented_already`, `residential.rented_elsewhere` minus its plain "not
  looking anymore"), an open visit, a chat a person holds, a stopped chat, or a lead closed already (`not_interested_at`).
  The rent flow's plain "no longer looking" (which it reads as rented elsewhere) gets the offer too, its
  `already_rented` dropped; the model's own `already_rented` in other words is trusted. A 2d "not a shop" chat
  (`facts.need`, already told "we have many options across Dubai") keeps the owner's never-Lost no (2026-10-15)
  without a second push. The offer's message is marked (`payload.offer`), and `followups.other_areas_pending` holds
  every nudge and Template B after it as a decline.
- **The backstop (`engine.area_decline`, in `settle`):** "not looking ... in that area anymore" / "no longer looking"
  is a no whatever the model tagged — only as the gist of the message: never in a question, never beside a want or
  another search ("..., I am looking in JVC for a studio"), never once the offer went (their answer to it is the
  model's to read), never with a visit booked or a person holding the chat; the area is tied to the negation ("not
  looking for properties in that area", never "... see you there" or "that place"). It only marks the answer: every
  guard after settle runs on the model's own answer, and at the dispatch the offer replaces the reply only when the
  turn is otherwise plain (`engine.plain_turn`: no handover, no line or step of code's, no booking); code's reading
  never produces a close. The reconnect list holds a chat whose newest words are the unanswered offer too.
- **The eval:** three strict scenarios, code's words (`shops-area-decline`, `shops-no-thanks-offer`,
  `shops-area-decline-again`), mirrored in `leadai_eval` (`code_first`, `run_once`, `outgoing`). The prompt is
  untouched.

## 6k. Round 27 (2026-10-24): a stopped chat takes itself up again; shop words stay on the shop track

- **Matloob's order (chats 54240 and 54325):** after an automatic message the AI stopped and stayed stopped however much
  the client wrote, until a person pressed Resume; after a manual Resume, "Yes I have ma shops" got the "many other
  options across Dubai, not only shops" line instead of the shop options.
- **The resume (`engine.resume_reason`, at `run_turn`'s stopped check):** an automatic-reply stop lifts on any tap, voice
  note, photo or file after it, or a text that is no automatic reply; the customer's own STOP lifts on a message of
  theirs at least 15 minutes later that is no acknowledgement, only when it was their own (the registry row
  `leadai_stop` / `inbox_tap`, no Opted out set by a person in Bitrix, never a deletion request in the chat's record).
  Never on words that ask to stop again; never after a wrong number or spam; an agent's Pause never lifts. The stop
  clears as the panel's Resume clears it; a STOP stays on the opt-out registry. A person's STOP replaces an
  automatic-reply stop (`record_opt_out`) and gets the confirmation line.
- **The shop words (`tracks.shop_words_only`):** a short answer about shops naming no other property and no letting,
  selling or buying is no other need under the model's `other_need` tag: the shop track.
- **Not changed:** a message skipped while stopped is not answered later by itself (the sweep never re-runs it); the
  lead's Bitrix Bot Status stays "Opted out" after a lift, as after the panel's Resume.

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
