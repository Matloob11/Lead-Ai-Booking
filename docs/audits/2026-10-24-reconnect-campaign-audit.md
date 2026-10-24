# Reconnect campaign audit (campaigns 681-689, sent 2026-10-23 12:50-13:50 UTC)

Written 2026-10-24 by Claude Code for Matloob. Read-only: the transcripts of the 77 chats that replied, judged one by one by
a review Workflow (8 readers and a synthesis), then checked against the database. Phone numbers are masked; chat ids are
conversation ids in the panel.

## Delivery

| | Recipients |
|---|---|
| In the audience | 1,222 |
| Sent (215 read, 162 delivered, 3 sent) | 380 |
| Skipped by our own rule after 12 Meta-cap fails in a campaign (`apps/campaigns/failures.py` MARKETING_CAP_PAUSE_AFTER) | 713 |
| Failed: Meta marketing cap (131049, per user) | 102 |
| Failed: undeliverable / experiment / provider | 25 |
| Opted out while waiting | 2 |
| The same phone sent twice from two of our numbers | 45 phones |

Of 507 attempts only 20% met the per-user cap, so most of the 713 skipped would probably have been delivered.
Today's campaigns 710-725 (2,004 recipients, started 12:23-12:54 UTC 2026-10-24) show the same pattern: 442 skipped by the
same rule by 12:55 UTC, 124 failed on Bitrix rate limits (crm.item.add 429 / local limit), 991 pending.

## Verdicts: 40 ok, 37 with an issue

## Issue groups (most severe first)

### [high] Office slots were pushed or repeated when the customer asked for something else (photos, options, another time) (4 chats)

- **Chats:** 54129, 54533, 54279, 54409
- **What happened:** 54129 asked for photos and details first and got the same two slots three times in about 2 minutes. 54533 said 'No slot' and got slots again, then asked us to send the options, which no one did. 54279 can only come on Sunday or after 9 PM and got the office hours repeated with no next step. 54409 asked for 2 pm and was offered 10:30 or 12:30.
- **Cause:** Every turn ends with two slots. No rule handles a refused slot or a 'send options/photos first' request, so the model offers times again. Nothing hands a listings request or an out-of-hours visit to a person, and the offered slots ignore the hour the customer named. In 54129, 'Evening' (most likely a typo for 'Event') was read as a time, and the shop photos were never sent.
- **Fixed since:** no
- **Quickest fix:** Code: after a refused slot or 'send me the options/photos', stop offering times (as the deferral rule already does), send the photos we have, and hand over to a person with an alert to send options. For Sunday or after hours, hand over to arrange a time. When they name an hour, offer that hour on the next open day. Agents now: send options to 54533 (window closes 16:26 UTC 10-24) and to 54129 (parking side, over 720 sq ft, up to 55k). Arrange a Sunday or late viewing for 54279.
- **Example:** 54533 [226239] 'No slot' -> [226240] slots again; [226242] 'Just send the options available' -> [226245] 'Our agent will confirm...', with no hand-off.

### [high] The first reply used the old lead record as if the customer had asked (a bare 'Hello' or 'Sold') (4 chats)

- **Chats:** 54353, 54309, 54503, 54566
- **What happened:** 'Sold' got 'Sure! Spain Cluster is a great choice...' and the chat moved to the sale track. 'Hello' and 'hello good evening' got 'Sure! One-bedrooms in England Cluster / Studios in Spain Cluster are around AED ...'. 54566 was quoted Emirates Cluster prices he never asked about, which led to his confused question.
- **Cause:** On the first reply, the track and cluster come from the old lead. The rent/sale opener (residential.pre_model_rule -> opener_text, which always starts 'Sure!') fires on any plain message, including a greeting or a lone 'Sold'.
- **Fixed since:** no
- **Quickest fix:** Code: skip the opener when the message is only a greeting or a single word that names no unit or deal. Send the what-need question instead, or 'You asked us earlier about a studio in Spain Cluster. Are you still looking?'. Read a bare 'Sold', 'Bought' or 'Purchased' as not looking and close politely.
- **Example:** 54353 [225499] 'Sold' -> [225504] 'Sure! Spain Cluster is a great choice, and we can check other clusters too. Are you looking for yourself or for a client?' (track=sale).

### [high] The campaign reached people it should not have (2 chats)

- **Chats:** 54150, 54391
- **What happened:** 54150 said she never enquired and that we are not allowed to contact her. 54391, a Serena lead, was told he had asked about International City and replied that this was wrong information.
- **Cause:** The September send script (ops/catalog/leadai-sept-reconnect.py) has no community check of its own, so a lead from another area got the International City template. 54150's number may be wrong or out of date in Bitrix.
- **Fixed since:** no. Rounds 26 and 27 do not touch the audience. The 10-24 old-6-month send already splits International City leads from the rest.
- **Quickest fix:** Campaign: check the lead's community before using an area template, as the old-6-month script does. Check 54150's lead (where it came from, any earlier complaint) and keep her off every list.
- **Example:** 54150 [225372] 'I never enquired about anything' / [225377] 'You're not allowed to contact me and you know that'.

### [high] The AI kept talking to a broker while a person had the chat (2 chats)

- **Chats:** 54241, 54240
- **What happened:** After the broker hand-off and the agent's own message, the AI answered the broker again. 54241 got 'I'm AR Properties' virtual assistant' and a second hand-off in the middle of the agent's 'are you agent ?' exchange. 54240 got 'Thanks for confirming you are an agent or owner', then a holding line in reply to 'No need / Ok / Thank you'.
- **Cause:** When a chat already has the Broker label (for example after someone pressed Resume), a broker reply only counts as an ordinary handover and does not pause the chat (engine.settle, broker_labelled). Any message from a person ends a handover (engine._run_claimed). A person had reopened both chats minutes before.
- **Fixed since:** no
- **Quickest fix:** Code: every broker turn pauses the chat (remove the broker_labelled exception), and a person's message never ends a broker handover. Agents: in broker chats, use Pause, not Resume.
- **Example:** 54241 [228751] AGENT 'are you agent ?' -> [228755] 'Yes' -> [228758] AI 'I'm AR Properties' virtual assistant... I will pass your details to our specialist team'.

### [high] A rent chat jumped to the 'other' track on a short answer and got the generic 'Visit our office' line (2 chats)

- **Chats:** 54566, 54240
- **What happened:** An engaged one-bedroom renter asked 'Only you have rooms in emirates cluster'. He got 'Visit our office and we'll give you the best option': no answer, no slots, and the balcony and move-in questions were dropped. 54240's 'Yes I have ma shops' got 'many other options across Dubai, not only shops' plus slots.
- **Cause:** tracks._OTHER_NOUNS includes 'room' (meaning a room or bed space), so 'rooms' used to mean apartments moved the chat to 'other'. The shop case was the same kind of misreading.
- **Fixed since:** partly (round 27): 'Yes I have ma shops' now stays on the shop track. 'rooms' is not covered.
- **Quickest fix:** Code: on an open rent or sale track, treat 'room(s)' in a question as no wish for a room or bed space. Switch tracks only on 'a room', 'bed space' or 'partition' said as a want. Agent: answer 54566 now (window open until 04:33 UTC 10-25): we have one-bedrooms in other clusters too; which one does he prefer?
- **Example:** 54566 [226432] 'Only you have rooms in emirates cluster' -> [226433] 'Visit our office and we'll give you the best option. Here's our location on the map.' (track=other).

### [high] A real tap after the customer's automatic reply went unanswered for about 20 hours (2 chats)

- **Chats:** 54241, 54325
- **What happened:** The customer's WhatsApp Business auto-reply stopped the chat. Their 'Yes, still looking' tap a few minutes later got no answer until a person replied the next morning.
- **Cause:** A chat stopped as auto_reply did nothing at all until someone pressed Resume.
- **Fixed since:** fully (round 27): an auto-reply stop now lifts on any tap or real message
- **Quickest fix:** Nothing to build. A chat that got stuck before 12:06 UTC 10-24 still needs a person to press Resume. Round 27's probe found one such chat (53028).
- **Example:** 54325 [225345] auto-reply 13:06 -> [225443] tap 'Yes, still looking' 13:10, no answer -> first answer [228001] from a person at 08:45 on 10-24.

### [high] A business's WhatsApp greeting was answered as if a customer had written it (1 chats)

- **Chats:** 54418
- **What happened:** 'Thank you for contacting Syed | DAMAC Lagoons Specialist! Will connect with you shortly' arrived 21 s after the template. It got a reply offering help with Damac Lagoons plus our office address. The chat is still open on the rent track, with facts taken from the sender's business name.
- **Cause:** rules.looks_like_auto_reply needs two weak phrases, or one phrase within 15 s. This greeting had only one ('thank you for contacting'; 'connect with you shortly' is not on the list) and came at 21 s.
- **Fixed since:** no
- **Quickest fix:** Code: add 'connect with you shortly', 'will connect with you' and 'contact you shortly' to rules.AUTO_REPLY_WEAK, and allow about 60 s for the first reply after a campaign template. Round 27 lifts a wrong auto-reply stop once a real person writes, so the wider net is safe. Agent: pause 54418 and clear its facts.
- **Example:** 54418 [225477] 13:12:18 greeting -> [225484] 'Thank you for your message, Syed. Our agent will be ready to assist you with properties in Damac Lagoons...'.

### [medium] The same person got the template twice from two of our numbers (8 chats)

- **Chats:** 54129, 54132, 54267, 54281, 54214, 54225, 54198, 54375
- **What happened:** Four people got the campaign twice. Dariush Dario's two sends were 10 s apart, and he then talked to two AI threads that described his shop differently. Saimyominkhaing's were 55 s apart, and he tapped Stop in both. Krish got the second one 7 s after his Stop (not verified as the same phone). Sana khan's were 13 min apart, with the same business greeting both times.
- **Cause:** The send script split the leads round-robin across the 8 numbers by lead row (leadai-sept-reconnect.py). Duplicates were only caught within one campaign's build. The 30-day check and the 'already talking' check only see sent rows and live chats, so campaigns built at the same time never see each other's phones.
- **Fixed since:** no. The 10-24 old-6-month script (campaigns 710-725) splits leads the same way.
- **Quickest fix:** Campaign: dedupe the audience by phone and lead before splitting it across numbers; this is one line in both send scripts. Before 710-725 go out, check whether any phone is queued in two of them. Agent: answer Dariush in one thread only.
- **Example:** 54129 [225009] campaign 684 at 12:52:06 and 54132 [225012] campaign 685 at 12:52:16, both 'Hi Dariush Dario'. He answered in both.

### [medium] Hand-offs to a person were never answered (7 chats)

- **Chats:** 54183, 54503, 54530, 54545, 54641, 54240, 54640
- **What happened:** Five brokers were told 'the concerned agent will come back to you' and heard nothing for about 21-22 h. In 54240, the person's only message sounded like the bot, and the broker's questions went unanswered. In 54640, an agent reopened a stopped chat and then left the customer's 'Not now' hanging.
- **Cause:** This is on the team side. Broker drafts are never sent automatically, and only 54180 and 54241 got the team's 'we do not work with agents'.
- **Fixed since:** no (team side)
- **Quickest fix:** Agents now: answer or close each chat before its window ends (UTC 10-24: 54183 13:08, 54641 13:29, 54640 13:44, 54545 14:02, 54530 14:11, 54503 14:46; 54240 is open until 11:23 on 10-25). After that, only a template can reach them. Rule: one agreed broker reply sent within the hour, plus a reminder when a hand-off is still unanswered after 2 h.
- **Example:** 54183 [225376] 13:07 'Let me pass your details to the concerned agent...' -> 'Sure' / 'Thank you' -> no reply from a person by 10-24 11:45.

### [medium] Leads who went quiet after our question got no check-in (5 chats)

- **Chats:** 54298, 54328, 54474, 54507, 54618
- **What happened:** Warm leads got no nudge: two renters who had been offered two slots, and three left on the what-need or unit question. Identical chats (54367, 54454) got their nudge at 10:00 Dubai time on 10-24.
- **Cause:** The cause is not visible in the export. Either our last message never reached WhatsApp (a nudge needs it sent, delivered or read), or followups.bitrix_blocks held it (the lead is in a closed stage, has a meeting or a person's Bot Status, or a person worked on it recently).
- **Fixed since:** no
- **Quickest fix:** Check the worker-leadai log for 'Lead AI nudge_1 for conversation N: ...' and the status of each chat's last message. Agents: send the check-in by hand while the window is open (UTC 10-24: 54298 13:05, 54328 13:08, 54618 13:34, 54507 14:00, 54474 16:21), otherwise send a template.
- **Example:** 54618 [225833] 13:34 'Great! What are you looking for...' -> nothing. 54367's identical question got [226746] at 06:00:38.

### [medium] What the customer said about the unit was lost or ignored (4 chats)

- **Chats:** 54303, 54129, 54279, 54325
- **What happened:** Several stated needs were never acknowledged or recorded: parking side only (54129, said twice), dedicated parking (54279), and Phase 1 at about 366 sq ft (54325). 54303 needs 900+ sq ft but was offered a 400-550 sq ft shop when he said the price was high, and the same reply skipped his 'Monday is ok'.
- **Cause:** There is no fact field for parking, phase or size wishes, and the model does not put them in notes. The price-objection line (claims._LOWEST) always quotes the cheapest type, whatever size the customer needs.
- **Fixed since:** no
- **Quickest fix:** Code: the price-objection line should quote the type that fits facts.size_sqft (Type 3, from AED 80,000, for 900+). Prompt: any wish without its own fact field goes in facts.notes and is acknowledged once. Agents: shortlist parking-side shops for 54129 and a shop of 900+ sq ft for 54303.
- **Example:** 54303 [226308] 'not less 900sqf' ... [226976] 'Price is high' -> [226979] 'Our lowest is Type 1, from AED 33,000 a year (400-550 sq ft)... Would that size work for you?'.

### [medium] The morning check-in pushed a visit before we knew what they wanted (3 chats)

- **Chats:** 54367, 54454, 54309
- **What happened:** Customers who never answered 'What are you looking for...' (or the rent for-whom question) got 'just checking in — shall I hold a slot for you to see the options today or on Monday?'.
- **Cause:** nudges.first_text only repeats the shops for-whom question. Any other open question gets the visit invite (_OPTIONS).
- **Fixed since:** no
- **Quickest fix:** Code: when our last message was the what-need question or the rent for-whom question, the nudge repeats it ('Hi X, just checking in — are you looking for a shop, a studio or a one-bedroom, to rent or to buy?'), the same way _FOR_WHOM_AGAIN works, and it does not count as an invitation.
- **Example:** 54454 [225617] what-need question unanswered -> [226748] 10-24 06:00 'Hi Habibullah, just checking in — shall I hold a slot for you to see the options today or on Monday?'.

### [medium] Short replies were misread because a phrase is missing from the code's word lists (3 chats)

- **Chats:** 54562, 54409, 54439
- **What happened:** 'Yup sure' in answer to the check-back was not taken as a yes: a question about the shop's business went instead, and the one-month follow-up was probably not set. 'other than emirates cluster' left Emirates recorded as the cluster he wants. A bare 'Purchased' would now get round 26's other-areas pitch (a risk; it did not happen).
- **Cause:** rules.ACCEPTANCES has 'yep' but not 'yup'. tracks._NEGATORS has no 'other than', and an empty cluster list does not clear the lead's old cluster. engine._HAS_PLACE needs 'already purchased' or 'purchased a ...'.
- **Fixed since:** no (the 'Purchased' risk came in with round 26)
- **Quickest fix:** One small code patch: add 'yup', 'yup sure', 'yeah sure' and 'sure thing' to ACCEPTANCES. Read 'other than X' and 'apart from X' as turning X down, and let that clear the cluster. Treat a bare 'Purchased' or 'Bought' as a place found elsewhere. Agent: set 54562's one-month check-back by hand.
- **Example:** 54562 [225691] 'Should I check back with you in a month?' -> [225705] 'Yup sure' -> [225711] 'Thanks! When you are ready, just let us know what business the shop is for...'.

### [medium] A polite first 'no' closed the lead as Lost (2 chats)

- **Chats:** 54622, 54113
- **What happened:** 'No I'm good thanks / We are not looking for properties in that area anymore' and 'I've decided to cancel my property search for now' both got the closing line, and the leads went Lost. Neither got the other-areas offer or the check-back question.
- **Cause:** Before round 26, the first typed no was tagged not_interested and closed the lead right away.
- **Fixed since:** partly (round 26): the first no now gets the other-areas offer, which is exactly 54622's case. But 'for now' should get the check-back question instead, and both leads are still Lost.
- **Quickest fix:** Code: a no that says 'for now', 'at the moment' or 'on hold' gets 'No problem! Should I check back with you in a month?'. Agents: reopen 54622 with the other-areas line (by template if the window has closed), and set a one-month check-back for 54113.
- **Example:** 54113 [225025] 'I've decided to cancel my property search for now' -> [225029] 'No problem, thank you for letting us know.' (lead Lost).

### [medium] A Stop tap sent together with Yes or a greeting got only the stop line (2 chats)

- **Chats:** 54640, 54240
- **What happened:** Stop followed 6 s later by 'Yes, still looking' (54640), and Stop followed 9 s later by 'Salam' (54240), got only 'Done, you won't receive more messages from us.'. People had to reopen both chats by hand.
- **Cause:** engine._burst_opt_out lets any Stop tap in a burst win, and the rest of the burst gets no answer.
- **Fixed since:** no (round 27 lifts the customer's own STOP only on a message 15+ minutes later)
- **Quickest fix:** Code: keep the stop, but when the same burst also has a Yes tap or a greeting, add one line: 'If you tapped Stop by mistake and are still looking, just reply here.' Let their reply to that line lift the stop.
- **Example:** 54640 [225839] tap 'Stop messages' 13:35:48 + [225840] tap 'Yes, still looking' 13:35:54 -> [225841] stop line only.

### [medium] 'Remove my number from your database' was handled as a plain STOP, not a data deletion (1 chats)

- **Chats:** 54150
- **What happened:** The angry recipient got the plain stop line. There was no deletion reply, no alert to the admins and no CRM to-do to delete her details.
- **Cause:** The engine (around line 3613) only checks residential.asks_deletion when no STOP was found, and 'remove my number' already counts as a STOP.
- **Fixed since:** partly (round 27): her words now count as a deletion, so the stop can never be lifted. The deletion alert and to-do still never went out.
- **Quickest fix:** Code: check asks_deletion before the plain STOP reading. Agent: delete her details in Bitrix by hand and tell the admins.
- **Example:** 54150 [225382] 'You better remove my number from your database' -> [225389] 'Done, you won't receive more messages from us.'.

### [medium] One reply took 7 minutes (1 chats)

- **Chats:** 54303
- **What happened:** 'not less 900sqf', sent at 17:11:27, was answered at 17:18:31. His other replies took 15-20 s, and no other chat was active at the time.
- **Cause:** Not visible in the export: possibly a slow or retried model call, or a held turn. It was not the hourly cap.
- **Fixed since:** no
- **Quickest fix:** Read the turn row and the worker-leadai log for message 226308 (model time, retries, queue wait). Cap retries so a reply never waits minutes.
- **Example:** 54303 [226308] 10-23 17:11:27 -> [226310] 17:18:31.

### [low] The campaign greeting used broken names (14 chats)

- **Chats:** 54120, 54168, 54177, 54194, 54220, 54298, 54317, 54325, 54339, 54418, 54510, 54526, 54573, 54578
- **What happened:** Messages opened with 'Hi S I A M A K S O H R A B I', 'Hi Z A R D A N G R O U P', 'Hi Syed | DAMAC Lagoons', 'Hi Adhith | TPH GROUP', 'Hi Hyunmi Lee (Abeer)', 'Hi Real Estate', 'Hi Mid town Real Estate', 'Hi AL TANEEN KRATE CENTER', 'Hi Amine La87', 'Hi Jen~', 'Hi M', 'Hi I.', 'Hi Eng - Ghaith Alzakout' and 'Hi Talal (بو عبدالرحمن)'.
- **Cause:** campaigns/crm_leads.lead_display_name keeps the whole contact name when it differs from the lead title, and _bad_greeting accepts any text with at least one letter.
- **Fixed since:** no
- **Quickest fix:** Code in lead_display_name: cut at '|' and '(', join letter-spaced names, drop symbols and digits, take the first word, and title-case it. Use 'there' for one or two letters, initials, or company words (Group, Real Estate, Properties, Center, LLC). The AI's own name filter already turned 'AL TANEEN KRATE CENTER' into 'Hi there' in 54510's nudge. Note: crm_leads.py has another session's uncommitted edits.
- **Example:** 54120 [224995] 'Hi S I A M A K S O H R A B I, this is Malik...'; 54418 [225466] 'Hi Syed | DAMAC Lagoons, ...'.

### [low] Small wording slips in the AI's replies (9 chats)

- **Chats:** 54328, 54279, 54298, 54132, 54409, 54566, 54325, 54391, 54530
- **What happened:** Examples: 'The office location is above' when the link is below; 'Our agent confirms...' when no agent had written; the same line twice in a row; two questions plus slots in one reply; 'you're looking for yourself a one-bedroom'; 'We have shops... too' to someone who had asked for a shop; no apology after 'wrong information'; 'our rental team' before the need was known.
- **Cause:** Mostly the model's wording. residential.handover_line defaults to the rental team, and the switch line always says 'too'.
- **Fixed since:** no
- **Quickest fix:** Code filters: drop 'Our agent confirms' when no agent has written, drop 'location is above' when the link is added below, and drop a sentence repeated from our last message. handover_line should say 'our team' while the track is unknown. Prompt: one question per reply, and apologise when the customer says our message was wrong.
- **Example:** 54328 [225400] '...which is better? The office location is above. / Our office location: https://maps.app.goo.gl/...'.

### [low] Visits were recorded with no agreed time (6 chats)

- **Chats:** 54129, 54279, 54303, 54409, 54530, 54533
- **What happened:** Each of these chats shows visits=1, but nobody accepted a slot or gave a full name. The visits came from 'Evening' (most likely 'Event'), 'Sunday' (office closed), 'Monday is ok', 'Sunday / 2 pm', 'We can chat on Monday when I'm back', and 'if ok we can meet'.
- **Cause:** By design, a day the customer names or words about coming keep a tentative visit in their words (engine.own_offer). This happens even for a closed day, a chat rather than a visit, or a conditional. Each one alerts the team and blocks nudges while it is open.
- **Fixed since:** no
- **Quickest fix:** Agents: check the 6 visit records and cancel the ones nobody agreed to (at least 54129, 54530 and 54533). Code: no tentative visit for a closed day, a conditional, or 'chat/call on <day>'.
- **Example:** 54530 [226020] 'We can chat on Monday when I'm back in Dubai' (turn skipped) -> visits=1, though no slot was ever offered.

### [low] Brokers and agencies in the list were not flagged as brokers (5 chats)

- **Chats:** 54241, 54418, 54325, 54194, 54120
- **What happened:** Agencies and agents answered with their own business greetings: Driven Properties, Mid Town Real Estate, 'Property Consultant', 'DAMAC Lagoons Specialist', 'I specialize in Dubai real estate'. None got the Broker label, so the agent had to ask 'are you agent ?', and they stay in future lists.
- **Cause:** The list only skips leads already marked Broker in Bitrix, and the AI does not read broker signals in an auto-greeting or a business name.
- **Fixed since:** no
- **Quickest fix:** Code: when an auto-greeting or the contact name contains agency words (Properties, Real Estate, Realty, Property Consultant, Specialist), add the Broker label and set Bot Status Broker in Bitrix, still without replying. The campaign builder already skips Bot Status Broker.
- **Example:** 54241 [225182] auto-reply signed 'Atif Bajwa / Property Consultant' -> no label; the agent later asked [228751] 'are you agent ?'.

### [low] Qualifying steps were skipped (2 chats)

- **Chats:** 54507, 54303
- **What happened:** After a bare 'Rent', 54507 was only asked 'studio or one-bedroom?' and never offered a shop. 54303 never answered the for-whom question but was recorded as buying for himself. He was never asked about his business, and the slot was not asked again after his price question was put off.
- **Cause:** After 'Rent', the rent flow assumes a home. The shop flow went straight from size to the licence. for_client was set without an answer.
- **Fixed since:** no
- **Quickest fix:** Code/prompt: after a bare 'Rent', ask 'a shop, a studio or a one-bedroom?'. Never record for_client without an answer. Ask about the business before the licence. After putting off a question, ask for the slot again.
- **Example:** 54507 [225603] 'Rent' -> [225608] for-whom -> [225955] 'Are you interested in a studio or a one-bedroom apartment?'.

## Every chat

| Chat | Verdict | Summary | Issues |
|---|---|---|---|
| 54113 | issue | The customer paused his search ('cancel my property search for now'). The AI closed the lead as lost instead of offering to check back. | wrong-stop (medium) |
| 54120 | issue | The reply was a WhatsApp Business greeting from a real-estate professional ('I specialize in Dubai real estate'). The AI was right to stay silent (auto_reply stop). Only the campaign greeting's name is broken. | campaign-name (low) |
| 54129 | issue | Same person as 54132 (Dariush Dario: shop over 720 sq ft, parking side, up to AED 55,000, events/equipment LLC). Discovery went well. Then 'Evening' was read as a visit time, the same two slots were offered three times, and his request for photos and details got a third slot offer instead. | pushed-visit-too-early (high); weird-reply (medium); fact-not-recorded (medium) |
| 54132 | issue | Duplicate of 54129: the same person got the template again from a second campaign 10 s later and talked to two AI threads at once. This one ends on a licence question he never answered here. | duplicate-campaign (medium); repeated-reply (low) |
| 54135 | ok | Tapped 'Stop messages' 40 s after the campaign and got the stop line 16 s later. Correct. | - |
| 54142 | ok | Tapped 'Stop messages' and got the stop line 14 s later. Correct. | - |
| 54150 | issue | Angry recipient: never enquired, 'not allowed to contact me', 'remove my number from your database'. The AI stopped and sent the stop line correctly. But the removal request was not handled as a data deletion, and she should not have been messaged at all. | campaign-to-wrong-person (high); deletion-missed (medium) |
| 54153 | ok | Tapped 'Stop messages' and got the stop line 15 s later. Correct. | - |
| 54168 | issue | A business's automatic greeting. The AI was right to stay silent (auto_reply stop). Only the campaign greeted the company as 'Z A R D A N G R O U P'. | campaign-name (low) |
| 54177 | ok | Tapped 'Stop messages' 5.7 min after the campaign and got the stop line 14 s later. Correct. The greeting's bracketed name 'Hyunmi Lee (Abeer)' is minor and the 54120 name clean-up covers it. | - |
| 54180 | ok | A broker wrote 'im looking for my client' and got the hand-off line in 18 s, and the chat paused. A person declined the next morning: 'we do not work with agents'. | - |
| 54183 | issue | Yes went to 'What are you looking for', then 'Rent / 1bhk' got the England 1BR band (cluster from the lead record), then 'For client' got the hand-off in 18 s. No person ever replied after that. | unanswered-after-handover (medium) |
| 54189 | ok | Tapped 'Stop messages' and got the stop line in 16 s. | - |
| 54194 | issue | The AI was right: the number's WhatsApp Business greeting stopped it with no reply. The problem is the recipient: the campaign went to a brokerage (Driven Properties) saved in the CRM as 'Real Estate'. | campaign-to-wrong-person (low) |
| 54198 | ok | The customer's WhatsApp Business greeting ('Thank you for contacting Sana khan!') came back. The AI did not reply and stopped the chat as an automatic reply. | - |
| 54214 | ok | Tapped 'Stop messages' and got the stop line in 15 s. See 54225: a 'Krish' got campaign 683 7 s after this Stop. | - |
| 54218 | ok | Yes got the open-lead question for the lead's 1BR, 'For myself' got the balcony/move-in question in 18 s, then the customer went quiet. One visit nudge went at 10:00 Dubai on the next open day, as designed (nudges.py 'options'). | - |
| 54220 | ok | Tapped 'Stop messages' and got the stop line in 15 s. | - |
| 54225 | issue | Tapped 'Stop messages' and got the stop line in 16 s. But this 'Krish' may be the same person as 54214, which would mean he got the same campaign from a second number 7 s after his Stop there. | duplicate-campaign (medium) |
| 54240 | issue | A Stop tap and 'Salam' 9 s later got only the stop line. A person reopened the chat the next day. The AI misread 'Yes I have ma shops' (sent the other-areas line and pushed a visit), handed over the broker (TZR Properties), then misread 'You agent / Ya owner' and sent a holding line to 'No need / Ok / Thank you'. Nobody answered his questions. | wrong-stop (low); wrong-track (medium, fixed since); weird-reply (medium); unneeded-reply (low); unanswered-after-handover (low) |
| 54241 | issue | Broker (his auto-reply is signed 'Property Consultant'). He tapped Yes and got nothing for 22 h because of the auto-reply stop. After an agent revived the chat, 'For client' got the broker hand-off. Then the AI cut into the agent's own exchange with the bot-identity line. | unanswered-after-stop (high, fixed since); ai-spoke-after-handover (high); broker-not-detected (low) |
| 54251 | ok | Tapped 'Not now' -> 'No problem! Should I check back with you in a month?' -> 'Yes, Thanks' -> 'Great, I'll check back with you then.' All correct. | - |
| 54258 | ok | Tapped 'Stop messages' 45 min after the campaign, got the stop line in 15 s, and the chat stopped (stop_all). | - |
| 54267 | ok | Tapped 'Stop messages' and got the stop line in 15 s. The same person also got campaign 683 in chat 54281 a minute later (the issue is recorded there). | - |
| 54279 | issue | Wanted a 1BR to rent for himself in France Cluster: December move, no balcony, dedicated parking. He was qualified quickly and sent photos. But when he said he can only come on Sunday or after 9 PM, the AI repeated the office hours and gave him no next step. | dead-end-visit (medium); fact-not-recorded (low); misleading-wording (low); other (low) |
| 54281 | issue | Same person as 54267 ('Hi Saimyominkhaing'). The template came again from campaign 683 55 s later, and he tapped Stop in both chats 10 s apart. The stop line itself was correct. | duplicate-campaign-send (medium) |
| 54288 | ok | Tapped 'Stop messages' 29 s after the campaign, got the stop line, and the chat stopped. | - |
| 54298 | issue | Wants a studio to rent with a balcony, pet friendly, moving next week. Qualified in 2 minutes, but the last reply crammed in a cluster question and a slot offer. He went quiet and no follow-up came. | missed-follow-up (medium); long-reply (low); campaign-personalization (low) |
| 54303 | issue | Wants a shop of at least 900 sq ft and has a DED licence. Got Type 3 from AED 80,000, then a nudge, and answered 'Monday is ok' and 'Price is high'. The AI offered a 400-550 sq ft shop, then put off the per-sq-ft price without settling the Monday time. One reply took 7 minutes. | slow-reply (medium); weird-reply (medium); missed-booking (low); skipped-question (low) |
| 54309 | issue | The customer only said 'Hello', 20 h after the campaign. The AI answered 'Sure!' with an England Cluster 1BR price as if he had asked, then sent a slot-push nudge 2 h later. No reply since. | weird-reply (medium); pushed-visit-too-early (low) |
| 54317 | ok | The customer tapped Stop messages 4h45m after the campaign and got the stop line. Their 'No' 2 minutes later was rightly left unanswered, and it is consistent with the stop. | - |
| 54319 | ok | The customer tapped Stop messages and got the stop line 14 seconds later. | - |
| 54325 | issue | A real-estate agency (Mid Town Real Estate). Its auto-greeting stopped the AI, so its 'Yes, still looking' tap waited about 19.5 hours until an agent answered. The AI then asked the shop for-whom question but ignored the details the customer gave. | unanswered-after-stop (high, fixed since); broker-not-detected (low); weird-reply (low) |
| 54328 | issue | The customer wants a studio to rent for himself, is moving next week and is flexible on cluster. The AI qualified him well and offered two slots today. The invite says the location is 'above' when it is below. No reply or nudge since. | weird-reply (low); other (low) |
| 54339 | ok | The customer tapped Stop messages and got the stop line. | - |
| 54341 | ok | 'Not now' got 'Should I check back with you in a month?'. 'i already got' then got 'No problem, thank you for letting us know.' and the chat was marked lost. That is correct, because a place found elsewhere closes the chat. | - |
| 54353 | issue | Asif replied 'Sold', which most likely means it is sold or he is no longer looking. Code put him on the sale track and answered 'Spain Cluster is a great choice'. | wrong-track (high) |
| 54367 | issue | The customer tapped Yes and got the what-are-you-looking-for question, then went quiet. The next morning's nudge pushed a visit 'to see the options' while the need is still unknown. | pushed-visit-too-early (medium) |
| 54375 | ok | Only a WhatsApp Business auto-greeting came back. The AI stopped and no person wrote after it. | - |
| 54391 | issue | A Serena lead got the International City campaign. He tapped Not now, then said it was wrong information. The AI asked about Serena without apologising. | campaign-to-wrong-person (medium); weird-reply (low) |
| 54405 | ok | Rose tapped Stop messages (225463) and got the stop line 16 s later. The chat is stopped (stop_all). | - |
| 54409 | issue | Sohail (open lead: studio in Emirates Cluster) tapped Yes. The AI checked who it was for, sent photos, asked about balcony and move-in, and offered two slots. He asked for Sunday 2 pm, was offered Monday 10:30 or 12:30, and said 'I will update you'. Every reply came fast, but the cluster he turned down is still recorded as his wish and his 2 pm was ignored. visits=1 is probably the tentative hold; no time was agreed. | fact-not-recorded (medium); ignored-preferred-time (low); repeated-reply (low) |
| 54418 | issue | The contact is another agency's 'DAMAC Lagoons Specialist'. Its WhatsApp Business greeting arrived 21 s after the campaign and was answered as if a customer wrote it, with Damac Lagoons help and our office address. The chat is still open on the rent track, with facts taken from the business name. | auto-reply-missed (high); weird-reply (medium); campaign-to-wrong-person (low) |
| 54426 | ok | Sinead tapped Stop messages (225631) and got the stop line 15 s later. The chat is stopped. | - |
| 54439 | ok | 'No need' plus 'Purchased' (bought elsewhere) got one closing line 20 s later and the lead was marked Lost. That was correct under the rules at the time. Round 26 could now get the same words wrong (see the low issue). | regression-risk (low) |
| 54443 | ok | Abdullah tapped Stop messages (225520) and got the stop line 15 s later. The chat is stopped. | - |
| 54450 | ok | Lina tapped Stop messages (226075) about an hour after the campaign and got the stop line 15 s later. The chat is stopped. | - |
| 54454 | issue | The customer tapped Yes and got 'What are you looking for...' 18 s later, then went quiet. The next-morning nudge invited him to a visit although we still do not know what he wants. | pushed-visit-too-early (medium) |
| 54456 | ok | Tanveer tapped Stop messages (225529) and got the stop line 16 s later. The chat is stopped. | - |
| 54462 | ok | Wasif tapped Stop messages (225543) and got the stop line 15 s later. The chat is stopped. | - |
| 54470 | ok | Tapped Stop messages 5 h after the campaign, got the stop line 14 s later, and the chat stopped. Correct. | - |
| 54474 | issue | Tapped Yes, still looking and got the right what-need question in 15 s. Then went quiet, and no check-in followed. | no-follow-up (low) |
| 54503 | issue | Said 'hello good evening'. Code's rent opener answered 'Sure! Studios in Spain Cluster…' from the old lead's enquiry. He is looking for a client, so the broker handover and pause were correct, but no agent has replied since. | weird-reply (low); agent-no-followup (medium) |
| 54507 | issue | Tapped Yes and typed 'Rent', for himself. The AI asked for-whom, then only 'studio or one-bedroom?', so a shop was never offered. He went quiet and no check-in went. | missed-shop-option (low); no-follow-up (low) |
| 54510 | ok | Yes -> what-need question -> 'Shop for rent' -> shop track and the for-whom question. He went silent, and the for-whom check-in went at 10:00 Dubai the next day. Correct. | - |
| 54518 | ok | Tapped Stop messages 30 s after the campaign and got the stop line 15 s later. Correct. | - |
| 54519 | ok | Tapped Stop messages and got the stop line 15 s later. Correct. | - |
| 54526 | ok | Tapped Stop messages 50 s after a campaign that greeted 'Adhith / TPH GROUP', and got the stop line 14 s later. The AI was correct; the campaign greeting was not. | campaign-name (low) |
| 54530 | issue | Yes -> what-need question. 'I'm in London right now' got the abroad handover naming the 'rental team' before the need was known. He then said he's back Monday and wants to buy a tenanted unit for a client (a broker). Chat paused; no agent reply; visits=1 with no booking. | wrong-track (medium); agent-no-followup (low); phantom-visit (low) |
| 54531 | ok | The business's WhatsApp auto-greeting (FIXATION HUB TECHNICAL SERVICES) replied. The AI stayed silent and stopped the chat as auto_reply, and no person wrote after. Correct. | - |
| 54533 | issue | The customer tapped Not now, then said they are looking in Dubai South and asked us to send options before meeting. The AI kept pushing office slots and promised options that nobody sent. | weird-reply (high); missed-handover (high); pushed-visit-too-early (medium) |
| 54545 | ok | A broker ("im looking for my client are you ok with sharing") got the broker line and was handed to a person (handed=t, paused=t), as the rules say. No AGENT message appears in the chat since the 10-23 14:02 handover. | - |
| 54548 | ok | The customer tapped Stop messages and got "Done, you won't receive more messages from us." within 14 s. The chat is stopped. | - |
| 54551 | ok | The customer tapped Stop messages and got the stop line within 15 s. The chat is stopped. | - |
| 54557 | ok | The customer tapped Stop messages and got the stop line within 15 s. The chat is stopped. | - |
| 54562 | issue | The customer tapped Not now and agreed to a check-back in a month ("Yup sure 😊"). That yes was not recognised, so the AI asked about the shop's business instead of confirming the check-back. | check-back-yes-missed (medium) |
| 54566 | issue | An engaged one-bedroom renter (for themselves) asked whether we have units only in Emirates Cluster. The AI switched the chat to the 'other' track and sent a generic "Visit our office" line without answering, so the flow died. | wrong-track (high); weird-reply (low) |
| 54573 | issue | The AI handled this correctly: Not now, then the check-back question, then "No. I already got what i need" closed the lead as Lost. Round 26 deliberately leaves out a place found elsewhere. Only the campaign greeting "Hi Jen~," is off. | campaign-greeting-name (low) |
| 54578 | issue | The AI followed the rules: Not now, then the check-back question, then "No." (check_back_no) closed the lead as Lost. Round 26 deliberately excludes the check-back's No. Only the campaign greeting "Hi I.," is off. | campaign-greeting-name (low) |
| 54601 | ok | The customer tapped Stop messages and got the stop line within 16 s. Their "Thank you" 11 s later was correctly left unanswered and the chat stays stopped. | - |
| 54603 | ok | Customer tapped Stop messages and got the stop line 15 s later. The chat is stopped, as the rules say. | - |
| 54618 | issue | Customer tapped Yes, still looking and got the what-need question in 15 s. He has been silent since, and no nudge followed, although identical chats got their first nudge at 10-24 06:00 UTC. | missed-nudge (medium) |
| 54620 | ok | Customer tapped Not now, then Stop messages 5 s later. The two taps were handled as one burst, and the customer got one stop line in 15 s. Stop winning here is correct. | - |
| 54622 | issue | Customer typed "No I'm good thanks" and then "We are not looking for properties in that area anymore". The AI closed with the not-interested line and marked the lead Lost, without offering other areas. | closed-on-first-no (medium, fixed since) |
| 54628 | ok | Not now got "Should I check back with you in a month?". Stop messages then got the stop line. A 👍 two minutes later correctly got no reply and did not lift the stop. | - |
| 54640 | issue | Customer tapped Stop messages and then, 6 s later, Yes, still looking. The AI answered the Yes with the stop line. An agent asked the what-need question 8 min later, the customer tapped Not now, and nobody answered that. | wrong-stop (medium); unanswered-after-stop (low) |
| 54641 | issue | Yes, still looking got the shop for-whom question. Going straight to it is by design, because the lead context says shop (tracks.first_yes). The customer said "I'm looking for my client", got the handover line, and the chat is now paused and handed over. The AI was correct throughout, but no agent has written since. | handover-no-followup (low) |

## Notes

77 chats replied: in 40 the AI did the right thing, and 37 have at least one issue. All 34 Stop taps got the stop line in about 15 s, the 6 automatic greetings got no reply, and every 'Not now' got the check-back question. 12 of the ok chats still appear in a group for a campaign-side or team-side problem (54177, 54198, 54214, 54220, 54267, 54317, 54339, 54375, 54439, 54510, 54526, 54545). Already fixed: the auto-reply tap (round 27, fully), 'Yes I have ma shops' (round 27), and the close on a first no (round 26, partly). A bare 'Purchased' is a new risk from round 26. Fastest wins: (1) Campaign, before the next send: dedupe by phone, check the community, clean up names, keep agencies out. The queued old-6-month campaigns 710-725 split leads the same way (ops/catalog/leadai-old6m-send.py). (2) Agents today: answer the 7 hand-offs and 5 quiet leads before their windows close, cancel the visits nobody agreed to, set 54562's check-back, and delete 54150's data. (3) One code round: keep broker chats silent, stop offering slots after a refusal, hand photo or listing requests to a person, skip the opener on a bare greeting or 'Sold', make the nudge repeat the open question, fix the word lists (yup, other than, purchased, for now), check deletion before STOP, add the auto-reply phrases, and add the name cleaner. Checked in the code: round-robin splitting with per-campaign dedupe, lead_display_name/_bad_greeting, AUTO_REPLY_WEAK and the 15 s window, ACCEPTANCES, _NEGATORS, 'room' in _OTHER_NOUNS, the deletion order, broker_labelled and the handover clear after a person writes, claims._LOWEST, nudges.first_text, nudge_due/bitrix_blocks. I added from the batch files (they were not in the verdicts): the Sana khan pair 54198/54375 (identical greeting) and the names in 54317 and 54339. Not verified: whether Krish 54214/54225 is one phone (the export has no phone numbers), why the 5 nudges did not go out, and what caused the 7-minute reply. Window times are the customer's last message + 24 h, so some may already have closed. Read-only: nothing edited and no command run. campaigns/crm_leads.py and leadai views.py/urls.py carry another session's uncommitted edits.
