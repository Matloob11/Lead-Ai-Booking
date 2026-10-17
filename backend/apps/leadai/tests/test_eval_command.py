"""leadai_eval: scripted chats, judged the way the engine acts on an answer.

The model is a fake here; the real run happens on the live server, with the
Lead AI key. These prove that every scenario is built like a live turn without
a single query, that nothing is sent or stored, that the verdicts and the
summary are printed, that --only filters, that a wrong answer is a FAIL with
exit status 1, that an OpenAI error fails a scenario instead of the run, and
that the command refuses to start without the key.
"""

import ast
import contextlib
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inbox.models import Message
from apps.leadai.assistant import openai_client, prompt, reminders, schema, transcript
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChatState, LeadAiTurn

MODEL = "apps.leadai.assistant.openai_client.complete_json"
SENDS = (
    "apps.inbox.services.send_text",
    "apps.inbox.services.send_location",
    "apps.inbox.services.send_buttons",
    "apps.inbox.services.send_template",
)
VERDICT = ("PASS", "FAIL")


def answer(reply="Great. What business activity will the shop be used for?", action="none", place=None, date=None, time=None, **extra):
    data = {
        "language": extra.pop("language", "en"),
        "segment": extra.pop("segment", "commercial_tenant"),
        "facts": {key: None for key in schema.FACT_KEYS},
        "appointment": {"action": action, "place": place, "date": date, "time": time, "customer_words": extra.pop("words", None)},
        "handover": {"needed": bool(extra.get("handover")), "reason": extra.pop("handover", None)},
        "opt_out": extra.pop("opt_out", "none"),
        "hot_lead": extra.pop("hot_lead", False),
        "invited_to_meeting": extra.pop("invited", False),
        "share_office_location": extra.pop("share_location", False),
        "send": extra.pop("send", True),
        "reply_en": extra.pop("reply_en", ""),
        "reply": reply,
    }
    data["facts"].update(extra.pop("facts", {}))
    assert not extra, extra
    return openai_client.Completion(data=data, model="gpt-4.1-mini", prompt_tokens=1000, completion_tokens=100, latency_ms=1)


def booked(day, clock, **extra):
    return answer("", action="confirm", place="office", date=day, time=clock, **extra)


SPECIALIST_REPLIES = "Thank you. Our specialist will reply to you here."

# What a right answer looks like for each scenario: each of these must pass.
RIGHT = {
    "shop-activity": answer(),
    "shop-licence": answer("Thank you. Do you already have a trade licence for it?", facts={"business_activity": "restaurant"}),
    "shop-no-licence": answer("No problem. Do you have the initial approval for it yet?", facts={"trade_licence": "no"}),
    "shop-invite": answer(
        "Thank you. Would you like to meet our commercial specialist at our office to go through the options?",
        facts={"trade_licence": "yes", "size_sqft": 400},
        invited=True,
    ),
    "shop-evening": answer("Great. Would 6 PM or 7 PM today work for you?"),
    "shop-tomorrow": answer("Great. Would 11 AM or 5 PM tomorrow suit you?", action="tentative", place="office", date="2026-10-13"),
    "shop-tomorrow-5pm": booked("2026-10-13", "17:00"),
    "shop-bare-5": booked("2026-10-13", "17:00"),
    "shop-sunday": answer(
        "Our office is closed on Sunday. We're open Monday to Saturday from 10 AM to 8 PM. Would Monday work for you?"
    ),
    "shop-9pm": answer("Our office closes at 8 PM. Would 7 PM or 7:30 PM work for you?"),
    "shop-outside-now": booked("2026-10-12", "14:00", hot_lead=True),
    "shop-injection": answer("Our office is closed on Sunday, so we cannot book that. Would Monday at 5 PM work for you?"),
    "shop-closed-day": answer("Our office is closed tomorrow. Would Wednesday at 5 PM work for you?"),
    "location-request": answer("Our office is in International City, here is the location.", share_location=True),
    "location-again": answer("You can find our office at the location above.", share_location=True),
    "yes-to-invite": answer("Great. Would 11 AM, 2 PM or 5 PM tomorrow work for you?", invited=True),
    "yes-to-slot": booked("2026-10-13", "17:00"),
    # Settled by code before the model (the deferral rule): never asked.
    "defer-message": answer("", send=False),
    "defer-massage": answer("", send=False),
    "shop-rent": answer(
        "Our specialist will confirm the rent with you. Would you like to visit our office to go through the options?",
        invited=True,
    ),
    "shop-rent-insisted": answer(SPECIALIST_REPLIES, handover="price_or_details_insisted"),
    "shop-photo": answer(SPECIALIST_REPLIES, handover="media_received"),
    "shop-broker": answer(SPECIALIST_REPLIES, handover="broker_or_for_client"),
    "who-is-this": answer("This is the A7 Real Estate team, about the shops for rent in International City. Are you looking for one?"),
    "are-you-a-bot": answer("I'm the team's virtual assistant, and a team member can take over any time. What is the shop for?"),
    "call-me": answer(SPECIALIST_REPLIES, handover="call_requested"),
    "complaint": answer("We're sorry about that. Our specialist will reply to you here.", handover="complaint_or_upset"),
    "asks-human": answer(SPECIALIST_REPLIES, handover="customer_asked_human"),
    "need-2br": answer("Sure. Are you looking to rent or to buy the 2BR?", segment="residential_tenant"),
    "stop-all": answer("Understood.", opt_out="stop_all"),
    "wrong-number": answer("Sorry.", opt_out="wrong_number"),
    "declines": answer("No problem.", opt_out="not_interested"),
    "away-message": answer("", send=False),
    "invites-exhausted": answer("Understood. Our specialist will reply to you here with the details.", handover="unclear"),
    "handed-over": answer("", send=False),
    "owner-viewing-slot": answer(
        "Thank you. Our specialist will confirm the viewing with you here.",
        action="tentative",
        place="customer_property",
        date="2026-10-14",
        time="16:00",
        handover="owner_viewing_slot",
        segment="owner",
    ),
    "owner-asks-client": answer(
        "Our specialist will share the details with you. Which day and time would suit you for the viewing?", segment="owner"
    ),
    "owner-sell": answer(
        "Thank you. Would you like to meet our specialist at our office to discuss the sale?",
        segment="owner",
        facts={"asking_price_aed": 450000, "occupancy_status": "vacant"},
        invited=True,
    ),
    "owner-abroad": answer(SPECIALIST_REPLIES, handover="abroad_cannot_visit", segment="owner"),
    "renewal-rent": answer(
        "Thank you. Our specialist will reply to you here with the renewal terms.",
        handover="renewal_terms",
        segment="renewal_tenant",
    ),
    "job-applicant": answer("Thank you. Our team will reply to you here about the interview.", handover="unclear", segment="other"),
    "lang-arabic": answer(
        "أهلاً بك. هل لديك رخصة تجارية للمطعم؟",
        language="ar",
        reply_en="Welcome. Do you have a trade licence for the restaurant?",
    ),
    "lang-roman-urdu": answer(
        "Shukriya. Kya aap ke paas trade licence hai?", language="ur_latin", reply_en="Thank you. Do you have a trade licence?"
    ),
    "lang-urdu": answer(
        "شکریہ۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟", language="ur", reply_en="Thank you. Do you have a trade licence?"
    ),
    "lang-hindi-latin": answer(
        "Dhanyavaad. Kya aapke paas trade licence hai?", language="hi_latin", reply_en="Thank you. Do you have a trade licence?"
    ),
    "lang-arabic-yes": booked("2026-10-13", "17:00", language="ar"),
    "lang-voice-urdu": answer(
        "Zaroor. Kal shaam 5 baje ya 6 baje theek rahega?",
        action="tentative",
        place="office",
        date="2026-10-13",
        language="ur_latin",
        reply_en="Sure. Would 5 PM or 6 PM tomorrow evening work?",
    ),
    "booked-reschedule": answer("", action="reschedule", place="office", date="2026-10-14", time="11:00"),
    "booked-running-late": answer("", action="running_late", time="17:30"),
    "booked-on-my-way": answer("", action="on_my_way"),
    "booked-cancel": answer("No problem, your meeting is cancelled. You can book another time whenever you like.", action="cancel"),
    "booked-same-time": answer("", send=False),
    "booked-ok-thanks": answer("", send=False),
    "booked-emoji": answer("", send=False),
    "exact-time": booked("2026-10-14", "17:00"),
    # The model records these tentative (as the prompt says); code must not book them.
    "exact-time-may": answer(
        "Sure. Shall I hold 5 PM tomorrow for you?", action="tentative", place="office", date="2026-10-13", time="17:00",
        words="I may come tomorrow at 5 pm",
    ),
    # Settled by code (the deferral rule, with a day and an hour beside it): never asked.
    "defer-with-time": answer("", send=False),
    # The shops playbook. Settled by code before the model (its own rules, the opt-out tap): never asked.
    "shops-yes-tap": answer("", send=False),
    "shops-not-now": answer("", send=False),
    "shops-not-now-yes": answer("", send=False),
    "shops-not-now-no": answer("", send=False),
    "shops-stop": answer("", send=False),
    "shops-broker": answer(SPECIALIST_REPLIES, handover="broker_or_for_client", facts={"for_client": True}),
    "shops-already-rented": answer(
        "Congratulations on your new shop! Do you need a second shop, or do you know someone who does?",
        facts={"already_rented": True},
    ),
    "shops-rented-no": answer("", send=False),  # settled by code
    "shops-rented-licence-no": answer(
        "No problem, many of our tenants open a new licence. What size do you need?",
        facts={"trade_licence": "no", "licence_kind": "new"},
    ),
    "shops-rent": answer(
        "Type 1 (400-550 sq ft) is AED 33,000-45,000 a year, Type 2 (600-800 sq ft) AED 48,000-65,000 and Type 3 "
        "(900-1,200 sq ft) AED 80,000-200,000. What business will the shop be for?"
    ),
    "shops-service-charge": answer(
        "Good question — I'll have our agent confirm that for you at the viewing. Do you have a DED or Trakhees licence, "
        "or will you open a new one?",
        facts={"notes": ["service charge"]},
    ),
    "shops-discount": answer("Our agent can discuss the best price for you at the viewing. Shall I hold today at 2:30 PM or 4:30 PM for you?"),
    "shops-sunday": answer("Our office is closed on Sunday. I can hold a slot for you on Monday at 11:00 AM or 5:00 PM — which is better?"),
    "shops-invite": answer(
        "Perfect, a new licence is fine for our shops. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?",
        facts={"licence_kind": "new", "trade_licence": "no"},
        invited=True,
    ),
    "shops-taken": answer("Sorry, 5:00 PM tomorrow is already booked. I can hold 4:30 PM or 5:30 PM tomorrow for you — which is better?"),
    "shops-arabic": answer(
        "أهلاً بك! هل المحل لك شخصياً، أم تبحث عنه لعميل؟",
        language="ar",
        reply_en="Welcome! Is the shop for yourself, or are you looking for it for a client?",
    ),
    "shops-roman-urdu": answer(
        "Zabardast, mobile ka kaam. Kya shop aap ke apne liye hai, ya kisi client ke liye?",
        language="ur_latin",
        reply_en="Great, a mobile business. Is the shop for yourself, or for a client?",
        facts={"business_activity": "mobile accessories"},
    ),
    "shops-35283": answer(
        "A vape shop, got it. For a vape shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED "
        "or Trakhees licence, or will you open a new one?",
        facts={"business_activity": "vape"},
    ),
    "shops-spam": answer("", send=False),  # settled by code (the spam rule): never asked
    # Batch 2b. The list, a type's media and the licence request replace the model's words.
    "shops-for-myself-list": answer("Great. What business will the shop be for?", facts={"for_client": False}),
    "shops-asks-types": answer("We have three types of shops, by size. What size do you need?"),
    "shops-photos": answer("Here are the photos of Type 1.", facts={"shop_type": "type_1"}),
    # The first live shops test (2026-10-15): our two slots record no visit; photos asked for after them go.
    "shops-invite-no-tentative": answer(
        "No problem, many of our tenants open a new licence. I can hold a slot for you today at 2:30 PM or 3:00 PM — which is better?",
        facts={"licence_kind": "new", "trade_licence": "no"},
        invited=True,
    ),
    "shops-photos-after-invite": answer("Sure, here are the photos of Type 2."),
    "shops-licence-ask": answer(
        "Perfect, a DED licence works for our shops. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?",
        facts={"licence_kind": "ded", "trade_licence": "yes"},
        invited=True,
    ),
    # Settled by code before the model (a tap on the list or a card, the licence copy alone): never asked.
    "shops-type-tap": answer("", send=False),
    "shops-type-tap-again": answer("", send=False),
    "shops-book-tap": answer("", send=False),
    "shops-other-types-tap": answer("", send=False),
    "shops-licence-copy": answer("", send=False),
    "shops-licence-copy-question": answer(
        "Yes, the shops are a few minutes from Dragon Mart. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?",
        invited=True,
    ),
    "shops-licence-later": answer(
        "No problem, please bring it with you. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?",
        invited=True,
    ),
    "shops-licence-send-later": answer(
        "No problem, send it whenever you are ready. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?",
        invited=True,
    ),
    "lang-inshallah-english": answer("See you tomorrow at 5 PM, Ahmed."),
    "shops-licence-second-page": answer("", send=False),  # settled by code (the copy's next page): never asked
    "shops-reschedule": answer("Sure. Which day and time would suit you instead?", action="reschedule"),
    # The model copies the prompt's old example; code puts the customer's own business in (board T56).
    "shops-vape-match": answer(
        "For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees "
        "licence, or will you open a new one?",
        facts={"size_sqft": 450, "shop_type": "type_1"},
    ),
    "lang-urdu-after-english": answer(
        "شکریہ۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟", language="ur", reply_en="Thank you. Do you have a trade licence?"
    ),
    "lang-hindi-devanagari": answer(
        "धन्यवाद। क्या आपके पास ट्रेड लाइसेंस है?", language="hi", reply_en="Thank you. Do you have a trade licence?"
    ),
    "lang-arabic-booking": booked("2026-10-13", "17:00"),
    "stop-arabic-after-english": answer("", send=False),  # settled by code (the stop rule)
    # Batch 2b stage B. Settled by code (Template B's taps, a known end user's yes): never asked.
    "shops-b-yes-tap": answer("", send=False),
    "shops-b-not-now": answer("", send=False),
    "shops-b-yes-known": answer("", send=False),
    "shops-a-yes-known": answer("", send=False),
    "shops-nudge-yes": answer(
        "Sure. I can hold a slot for you today at 5:00 PM or 6:30 PM — which is better?",
        action="tentative",
        place="office",
        date="2026-10-12",
        words="this evening",
    ),
    "shops-nudge-morning-pick": booked("2026-10-13", "13:00"),
    "shops-old-lead": answer("Thanks! What business will the shop be for?", facts={"for_client": False}),
    "shops-crm-notes-data": answer("A grocery store, got it. What size do you need?", facts={"business_activity": "grocery store"}),
    # The launch (2026-10-15): the model's answers as the live turns recorded them (chat_<id>.json: the turn's
    # actions and the facts it left). Code then decides who the customer is (engine.who_they_are).
    "shops-want-studio-44": answer(
        "Great! What business will the shop be for?",
        facts={
            "for_client": False, "property_type": "shop", "business_activity": "apartment studio", "intent": "rent", "abroad": False,
            "customer_name": "Trezah", "notes": ["fit-out requirements", "parking availability"],
        },
    ),
    "shops-want-1bhk-49": answer(
        "Great! What business will the shop be for?",
        facts={
            "for_client": False, "property_type": "shop", "business_activity": "room", "intent": "rent", "bedrooms": "1bhk",
            "community": "England", "customer_name": "محمد", "notes": ["size needed", "budget", "licence kind"],
        },
    ),
    "shops-no-shop-room-50": answer(
        "Noted, a room. What business will the shop be for?",
        facts={"for_client": False, "property_type": "room", "intent": "rent", "customer_name": "Ejas", "notes": ["Is a room available for rent?"]},
    ),
    "shops-studio-monthly-57": answer(
        "Great! What business will the shop be for?",
        facts={
            "for_client": False, "property_type": "studio", "business_activity": "studio", "intent": "rent", "budget_basis": "per_month",
            "customer_name": "sukirtha", "notes": ["monthly rent details"],
        },
    ),
    "shops-we-got-one-63": answer(
        "Congratulations on your new shop! Is it in International City?",
        facts={"for_client": False, "property_type": "shop", "intent": "rent", "already_rented": True, "customer_name": "Jerin"},
    ),
    "shops-not-now-studio-68": answer(
        "I see, a studio. Our shops are for retail or commercial use. Is the studio for a business activity?",
        facts={
            "for_client": False, "property_type": "studio", "business_activity": "studio", "intent": "rent", "customer_name": "swathy",
            "notes": ["Is a studio allowed in International City shops?"],
        },
    ),
    "shops-never-asked-98": answer(
        "I see, thanks for clarifying. Is the shop for yourself, or are you checking for a client?",
        facts={"property_type": "shop", "intent": "rent", "customer_name": "Raja", "notes": ["Is the shop for yourself, or are you checking for a client?"]},
    ),
    "shops-studio-balcony-107": answer(
        "Great! What business will the shop be for?",
        facts={
            "for_client": False, "property_type": "studio apartment", "intent": "rent", "customer_name": "Mohit",
            "notes": ["Is a studio apartment with balcony suitable for your business?"],
        },
    ),
    "shops-did-not-ask-114": answer(
        "Sorry for the confusion. Is the shop for yourself, or are you checking for a client?",
        facts={"intent": "rent", "notes": ["Is the shop for yourself, or are you checking for a client?"]},
    ),
    "shops-asked-for-studio-132": answer(
        "Great! What business will the shop be for?",
        facts={"for_client": False, "property_type": "studio", "intent": "rent", "customer_name": "Mojish", "notes": ["studio availability"]},
    ),
    "shops-buyer-42": answer(
        "You mentioned buying a shop. Is the shop for yourself, or are you checking for a client?",
        facts={"intent": "buy", "property_type": "shop", "customer_name": "MANAGER", "notes": ["Is the shop for yourself, or are you checking for a client?"]},
    ),
    # Turn 75 live: the buyer closed as not interested (Bitrix Lost, stage "1").
    "shops-buyer-not-lost-42": answer(
        "No problem, thank you for letting us know.",
        opt_out="not_interested",
        facts={"intent": "buy", "for_client": False, "property_type": "shop", "customer_name": "MANAGER"},
    ),
    "shops-residential-room-105": answer(
        "Our shops are for commercial use in International City. Are you looking for a shop for a business, or a residential room elsewhere?",
        handover="unclear",
        facts={"for_client": False, "property_type": "residential room", "intent": "rent", "customer_name": "Road", "notes": ["Is residential room available?"]},
    ),
    "shops-studio-capitals-136": answer(
        "We specialize in shops in International City. For studio apartments, I will connect you to our agent who can assist you further here.",
        handover="unclear",
        segment="other",
        facts={"for_client": False, "property_type": "studio apartment", "intent": "rent", "customer_name": "Appu"},
    ),
    "shops-studio-not-interested": answer("No problem, thank you for letting us know.", opt_out="not_interested", facts={"property_type": "studio"}),
    "shops-want-flat-arabic": answer(
        "عذراً على اللبس. هل تبحث عن شقة للإيجار في المدينة العالمية؟",
        language="ar",
        reply_en="Sorry for the confusion. Are you looking for a flat for rent in International City?",
        handover="wrong_need",
        facts={"property_type": "flat", "intent": "rent"},
    ),
    "shops-want-flat-roman-urdu": answer(
        "Samajh gaya, aap ko flat chahiye. Kya aap kisi khaas area mein dhoond rahe hain?",
        language="ur_latin",
        reply_en="Understood, you need a flat. Are you looking in a particular area?",
        facts={"property_type": "flat", "intent": "rent"},
    ),
    "shops-options-nudge-yes": answer("Great! I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?"),
    "shops-not-a-shop-booked": booked("2026-10-12", "16:30"),
    # Batch 2d, the follow-ups: chat 63's words to the second-shop question are code's (RENTED_NO); a referral is the model's.
    "shops-rented-soft-no-63": answer("", send=False),
    "shops-rented-reach-out-63": answer("", send=False),
    "shops-rented-friend-63": answer(
        "That's great! Your friend is welcome to message us here, and we'll help them find the right shop.",
        facts={"already_rented": True, "for_client": False, "property_type": "shop", "intent": "rent", "customer_name": "Jerin"},
    ),
    # Chat 100's "Ok" to the nudge: the two free slots (live, turn 132 asked for the business, licence and size instead).
    "shops-nudge-ok-100": answer(
        "Great, Saif! I can hold a slot for you today at 2:30 PM or 4:30 PM to see the Type 2 shops — which is better?",
        facts={"for_client": False, "property_type": "shop", "intent": "rent", "community": "Morocco", "shop_type": "type_2"},
    ),
    # Chat 78's own words to the nudge (turn 126 live sent the list), here after the nudge that asked for whom again (chat 103).
    "shops-for-whom-again-103": answer(
        "Great! What business will the shop be for?", facts={"for_client": False, "property_type": "shop", "intent": "rent", "customer_name": "huzefa"}
    ),
    # Where a person must act (people.py): code writes what goes out; the model's own words are judged nowhere.
    "shops-call-time-88": answer(
        "Sure, I'll pass your call request to our agent.", action="tentative", place="call", date="2026-10-15", time="11:30",
        words="We can have a call at 11.30 - 12 PM", handover="call_requested",
    ),
    "shops-call-chase-88": answer("", send=False),
    "shops-goodbye-57": answer("", send=False),
    "shops-must-answer-95": answer(
        "Thank you for the detailed questions. Our agent will answer them here before the visit.",
        handover="legal_visa_licence_contract", facts={"for_client": False, "business_activity": "small dessert takeaway and production kitchen"},
    ),
    "shops-gas-chimney-91": answer(
        "Our agent will confirm the gas line and the chimney for you here before the visit.", handover="legal_visa_licence_contract"
    ),
    "shops-computation-78": answer(
        "Our agent will send you the full cost breakdown here.", handover="legal_visa_licence_contract",
        facts={"budget_aed": 33000, "budget_basis": "per_year", "for_client": False},
    ),
    # Batch 2d, facts, slots and booking: the model's live answers, which code now puts right (claims.py, offers.py,
    # engine.book_window, discovery_first, tap_with_words); each fails without its guard (test_facts_slots_booking).
    "shops-same-day-window-96": answer(
        leadai_eval.CLAIM_96, action="tentative", place="office", words="barah saadhay barah baje ja ke check kar loon ga", language="ur_latin",
        reply_en="The location of the shop in England cluster is our office address. Which time is better for you?", invited=True,
        share_location=True, facts=leadai_eval.FACTS_96,
    ),
    "shops-building-and-past-slot-96": answer(
        leadai_eval.SIDE_96, action="tentative", place="office", words="barah saadhay barah baje ja ke check kar loon ga", language="ur_latin",
        reply_en="Yes, the shop is in Russia Cluster near Building V03, on the parking side, not the front side. Do you want to confirm 12:30 PM?",
        facts={**leadai_eval.FACTS_96, "notes": ["which building for 550 sq ft shop in England cluster"]},
    ),
    "shops-food-claim-91": answer(leadai_eval.FOOD_91, share_location=True, facts=leadai_eval.FACTS_91),
    "shops-commission-78": answer(
        leadai_eval.NO_COMMISSION_78, facts={"for_client": False, "budget_aed": 33000, "budget_basis": "per_year", "business_activity": "interior landscape"}
    ),
    "shops-rent-higher-59": answer(
        leadai_eval.DISCOUNT_59, action="tentative", place="office", words="Your rent is higher than others", invited=True,
        facts={"for_client": False, "customer_name": "ETS"},
    ),
    "shops-cheaper-100": answer(leadai_eval.DISCOUNT_100, invited=True, facts=leadai_eval.FACTS_100),
    "shops-tap-and-question-81": answer(
        "Our rents are per year: Type 1 starts from AED 33,000 a year, payable in 1 to 4 cheques. What size do you need?",
        facts={"property_type": "shop", "intent": "rent", "customer_name": "Imtiyaz", "notes": ["monthly rent calculation"]},
    ),
    "shops-tap-type-with-words-88": answer(
        leadai_eval.MATCH_88, invited=True, share_location=True,
        facts={"for_client": False, "community": "France", "size_sqft": 400, "shop_type": "type_1", "customer_name": "Abd"},
    ),
    "shops-invitation-cut-88": answer(
        leadai_eval.MATCH_88, invited=True, share_location=True,
        facts={"for_client": False, "community": "France", "size_sqft": 400, "customer_name": "Abd"},
    ),
    "shops-table-repeat-91": answer(leadai_eval.TABLE_91, facts=leadai_eval.FACTS_91),
    "shops-figures-asked-42": answer(leadai_eval.BUYER_42[6][1], facts={"for_client": False, "property_type": "shop", "intent": "rent"}),
    "shops-discovery-second-invite-62": answer(leadai_eval.AGAIN_62, invited=True, facts={**leadai_eval.FACTS_62, "licence_kind": "new"}),
    "shops-new-one-62": answer(
        leadai_eval.NEW_ONE_62, action="tentative", place="office", date="2026-10-15", time="11:00", words="One", invited=True,
        share_location=True, facts={**leadai_eval.FACTS_62, "licence_kind": "new", "trade_licence": "no"},
    ),
    "shops-location-counted-81": answer(
        leadai_eval.LOCATION_81, share_location=True, facts={"for_client": False, "customer_name": "Imtiyaz"}
    ),
    # Batch 2d, the CRM writes: the model's live answers, whose facts code now keeps to the customer's own (crm_facts.py);
    # each fails without it (test_crm_writes). Chat 120's "No thankyou" is code's now (rules.py): never asked.
    "shops-notes-theirs-88": answer(
        "No problem, many tenants open a new licence. Our agent will guide you through the process. I can hold a slot for you "
        "today at 11:30 AM or 12:00 PM — which is better?",
        invited=True,
        facts={
            **leadai_eval.FACTS_88,
            "notes": ["what business the shop is for", "size needed", "budget", "licence kind", "fit-out details", "service charge", "DEWA", "parking"],
        },
    ),
    "shops-budget-ours-62": answer(
        "Photos help, but seeing 2-3 shops side by side is much easier. I can hold a slot for you today at 11:00 AM or 11:30 AM at "
        "our office. Which is better?",
        action="tentative", place="office", date="2026-10-15", time="11:00", words="If possible to send me photo first", invited=True,
        facts={
            **leadai_eval.FACTS_62, "licence_kind": "new", "trade_licence": "no", "budget_aed": 48000,
            "notes": ["service charge", "DEWA", "parking", "fit-out"],
        },
    ),
    "shops-no-thankyou-120": answer("", send=False),
    # Batch 2d's review: shop customers' words that look like a want, a count, a call or a contract.
    "shops-review-shop-with-room": answer("A salon, got it. Is the shop for yourself, or are you checking for a client?", facts={"business_activity": "salon"}),
    "shops-review-flat-nahi": answer("Zaroor. Kya yeh shop aap ke apne liye hai, ya kisi client ke liye?", language="ur_latin"),
    "shops-review-staff-accommodation": answer("Sure. Is the shop for yourself, or are you checking for a client?"),
    "shops-review-count-no-window": answer(
        "Great, all of you are welcome. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", invited=True,
    ),
    "shops-review-sign-contract-today": answer("Great! I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", invited=True),
    "review-why-did-you-call": answer(
        "This is A7 Real Estate: we sent you a message about properties in Dubai. Are you looking to rent, buy or sell?", segment="other",
    ),
    "shops-review-call-back-later": answer("No problem, drive safe. Message us here whenever you are free."),
    "shops-review-studio-call-me": answer("Sure, our agent will call you shortly.", segment="residential_tenant", facts={"property_type": "studio"}),
    "shops-review-rented-one-more": answer("Great, one more shop. What business will it be for?", facts={"for_client": False}),
    "shops-review-buyer-no-rent-42": answer(
        "Thanks for clarifying. Currently, we only have shops available for rent, not for sale. Are you interested in renting a shop "
        "instead, or do you know someone who is?",
        facts={"intent": "buy"},
    ),
    "shops-review-studio-not-shops-68": answer(
        "I see, a studio. Our shops are for retail or commercial use, not residential studios. Is the studio for a business activity?",
        segment="residential_tenant",
    ),
    "shops-nine-questions-noted-95": answer(
        "Thank you for the detailed questions. Our agent will answer them here before the visit.",
        handover="legal_visa_licence_contract",
        facts={"for_client": False, "business_activity": "small dessert takeaway and production kitchen", "notes": list(leadai_eval.NOTES_95)},
    ),
    # The launch gate's review: what the gate's own fixes misread (test_gate_review_2d holds each without its fix).
    "shops-gate-slot-two": booked("2026-10-13", "13:00"),
    "shops-gate-after-work": booked("2026-10-13", "19:00"),
    "shops-gate-rented-another": answer(
        "Congratulations on your new shop! Do you need a second shop, or do you know someone who does?", facts={"already_rented": True}
    ),
    "shops-gate-location-question": answer(
        "International City is right next to Dragon Mart, which brings many visitors. What size of shop do you need?",
        facts={"for_client": False, "business_activity": "restaurant"},
    ),
    "shops-gate-half-hour": booked("2026-10-12", "16:30"),
    # Batch 2e slice A: the mixed template's first answer is code's (never asked); the track traps keep 2d's answers.
    "shops-mixed-yes-tap": answer("", send=False),
    "shops-mixed-typed-yes": answer("", send=False),
    "shops-mixed-yes-studio-lead": answer("", send=False),
    "shops-mixed-yes-1br-lead-arabic": answer("", send=False),
    "shops-mixed-yes-shop-lead": answer("", send=False),
    "shops-mixed-yes-buyer-lead": answer("", send=False),
    "shops-mixed-yes-known-shop": answer("", send=False),
    "shops-mixed-yes-known-studio": answer("", send=False),
    "shops-mixed-not-now": answer("", send=False),
    "shops-mixed-stop": answer("", send=False),
    "shops-track-shop-yes": answer("", send=False),
    "shops-track-photo-studio": answer("A photo studio, got it. Is the shop for yourself, or are you checking for a client?", facts={"business_activity": "photo studio"}),
    "shops-track-room-at-the-back": answer("Sure, a back room for storage. Is the shop for yourself, or are you checking for a client?"),
    "shops-track-live-in-a-studio": answer(
        "A mobile business, got it. Is the shop for yourself, or are you checking for a client?", facts={"business_activity": "mobile phones"}
    ),
    "shops-track-1br-near-my-shop": answer("Great! What business will the shop be for?", facts={"property_type": "shop"}),
    "shops-track-room-and-hall-arabic": answer(
        "عذراً على اللبس. هل تبحث عن شقة للإيجار في المدينة العالمية؟",
        language="ar",
        reply_en="Sorry for the confusion. Are you looking for a flat for rent in International City?",
        handover="wrong_need",
        facts={"property_type": "flat", "intent": "rent"},
    ),
    "shops-track-one-bed": answer("Great! What business will the shop be for?"),
    # The model writes the nationality as the community: code never reads it as China Cluster.
    "shops-track-from-china": answer("Great! What business will the shop be for?", facts={"community": "China"}),
    "shops-track-studio-sale-listing": answer("Great! What business will the shop be for?"),
    "shops-track-englund-1bhk-49": answer(
        "Great! What business will the shop be for?",
        facts={"for_client": False, "property_type": "shop", "business_activity": "room", "intent": "rent", "bedrooms": "1bhk", "community": "England"},
    ),
    "shops-track-continuity-448": booked("2026-10-12", "17:00"),
    "shops-track-villa-jvc": answer("Great! What business will the shop be for?"),
    "shops-track-2br": answer("Great! What business will the shop be for?"),
    # Batch 2e, the CRM: what a studio or one-bedroom chat writes to its lead (crm_fields.residential_writes).
    "shops-crm-rent-studio-spain": answer("Great! What business will the shop be for?", facts={"community": "Spain Cluster"}),
    "shops-crm-for-myself-move-in": answer(
        "Perfect, next month. Our agent will meet you at our office and take you to the available apartments.",
        segment="residential_tenant",
        facts={"for_client": False, "move_in": "next month"},
    ),
    "shops-crm-2br-writes-nothing": answer("Great! What business will the shop be for?"),
}


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


@override_settings(LEADAI_OPENAI_API_KEY="test")
class EvalCommandTests(TestCase):
    def call(self, *args, exit_status=None):
        """The command's output; ``exit_status`` when it must end with that CommandError."""
        out = StringIO()
        if exit_status is None:
            call_command("leadai_eval", *args, stdout=out, stderr=StringIO(), no_color=True)
        else:
            with self.assertRaises(CommandError) as raised:
                call_command("leadai_eval", *args, stdout=out, stderr=StringIO(), no_color=True)
            self.assertEqual(raised.exception.returncode, exit_status)
        return out.getvalue()

    def verdicts(self, text):
        return [row for row in text.splitlines() if row.startswith(VERDICT)]

    def test_every_scenario_is_built_like_a_live_turn_without_a_query(self):
        ids = [s.id for s in leadai_eval.SCENARIOS]
        self.assertGreaterEqual(len(ids), 40)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(RIGHT))
        with self.assertNumQueries(0):
            built = {s.id: leadai_eval.build(s) for s in leadai_eval.SCENARIOS}
        for s in leadai_eval.SCENARIOS:
            with self.subTest(s.id):
                self.assertRegex(s.id, r"^[a-z0-9-]+$")  # safe for a wrapper to pass on as --only
                self.assertTrue(s.expect or s.words == leadai_eval.SILENT)
                self.assertIn(s.words, (leadai_eval.MODEL, leadai_eval.EITHER, leadai_eval.SILENT, leadai_eval.CODE))
                context = built[s.id].context
                self.assertTrue(context.startswith(f"NOW: {s.now:%a %Y-%m-%d %H:%M} (Dubai)"))
                self.assertIn("\nCAMPAIGN MESSAGE: (sent ", context)
                conversation = context.split("CONVERSATION (oldest first):\n", 1)[1].split("\n\nNEW SINCE YOUR LAST REPLY", 1)[0]
                rows = [json.loads(row) for row in conversation.splitlines()]
                self.assertEqual(rows[0]["from"], "campaign")
                for row in rows:
                    self.assertEqual(list(row), ["from", "at", "text"])
                    self.assertIn(row["from"], {"customer", "assistant", "agent", "campaign", "reminder"})
                new = [json.loads(row) for row in context.split("NEW SINCE YOUR LAST REPLY (answer these):\n", 1)[1].splitlines()]
                # As live (transcript.line), a line holds LINE_MAX characters: chat 95's nine questions are longer.
                self.assertEqual([row["text"] for row in new], [text[: transcript.LINE_MAX] for text in s.new])
                self.assertEqual(rows[-len(new):], new)  # as live, the conversation already holds them
        self.assertIn("Tue 2026-10-13 (tomorrow): CLOSED", built["shop-closed-day"].context)
        late = built["booked-running-late"].context
        self.assertIn("OPEN APPOINTMENT: confirmed for Monday 12 October 2026, 5:00 PM at our office (customer is running late)", late)
        self.assertIn("EVENTS:\n- The customer told us: running late.", late)
        self.assertIsNone(built["booked-running-late"].appointment.pk)  # unsaved, and it stays so
        self.assertIn("SEGMENT HINT: record: Owner Data card (a property owner); campaign template:", built["owner-viewing-slot"].context)
        self.assertIn("HANDED OVER: yes (call_requested)", built["handed-over"].context)
        self.assertIn("INVITES SO FAR: 2", built["invites-exhausted"].context)

    def test_conversation_lines_are_the_ones_transcript_writes(self):
        moment = leadai_eval.NOW
        customer = Message(direction=Message.Direction.INBOUND, kind=Message.Kind.TEXT, body="Tomorrow 5pm", created_at=moment)
        self.assertEqual(leadai_eval.line("customer", moment, "Tomorrow 5pm"), transcript.line(customer, set()))
        ours = Message(
            direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body="Would 5 PM work?", payload={"source": "leadai_ai"}, created_at=moment
        )
        self.assertEqual(leadai_eval.line("assistant", moment, "Would 5 PM work?"), transcript.line(ours, set()))
        start = leadai_eval.at(12, 17)
        buttons = [{"type": "reply", "reply": {"id": action, "title": title}} for action, title in reminders.BUTTONS]
        reminder = Message(
            pk=7,
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.INTERACTIVE,
            body=leadai_eval.reminder_body(start),
            payload={"source": "leadai_reminder", "interactive": {"type": "button", "action": {"buttons": buttons}}},
            created_at=moment,
        )
        self.assertEqual(leadai_eval.line("reminder", moment, leadai_eval.reminder_line(start)), transcript.line(reminder, set()))
        tap = Message(
            direction=Message.Direction.INBOUND,
            kind=Message.Kind.INTERACTIVE,
            body="Running Late",
            payload={"interactive": {"type": "button_reply", "button_reply": {"id": "x", "title": "Running Late"}}},
            reply_to=reminder,
            created_at=moment,
        )
        self.assertEqual(
            leadai_eval.line("customer", moment, leadai_eval.tapped_on_reminder("Running Late", start)), transcript.line(tap, set())
        )

    def test_the_reply_readers(self):
        offered = leadai_eval.offered_times
        self.assertEqual(offered("Would 6 PM or 7:30 PM work? We're open Monday to Saturday, 10 AM to 8 PM."), [(18, 0), (19, 30)])
        self.assertEqual(offered("Kal 5 baje theek hai? Hum subah 10 se raat 8 baje tak khule hain."), [(17, 0)])
        self.assertEqual(offered("Your meeting is on 13 October, for 400 sq ft. We close at 8 PM."), [])
        self.assertEqual(offered("Would tomorrow at 5 suit you, or at 11?"), [(17, 0), (11, 0)])
        self.assertEqual(
            leadai_eval.amounts("AED 45,000, or 45k, or 45000, in 2026, for 1500 sq ft, near Riyadh 3"), ["AED 45,000", "45k", "45000"]
        )
        run = leadai_eval.Run(scenario=scenario("lang-urdu"), label="lang-urdu", reply="شکریہ۔ کیا آپ کے پاس لائسنس ہے؟")
        self.assertIsNone(leadai_eval.script("urdu")(run))
        self.assertIsNone(leadai_eval.one_question()(run))
        run.reply = "شكرا. هل لديك رخصة؟ ومتى تريد الحضور؟"  # Arabic, not Urdu, and two questions
        self.assertEqual(leadai_eval.script("urdu")(run), "reply is not in Urdu script")
        self.assertIsNone(leadai_eval.script("arabic")(run))
        self.assertEqual(leadai_eval.script("latin")(run), "reply is not in English letters")
        self.assertEqual(leadai_eval.one_question()(run), "asks 2 questions")

    def test_a_right_answer_passes_every_scenario(self):
        for s in leadai_eval.SCENARIOS:
            with self.subTest(s.id), patch(MODEL, return_value=RIGHT[s.id]):
                run = leadai_eval.run_once(s, s.id)
                self.assertEqual(run.failures, [])

    def test_a_full_run_queries_nothing_sends_nothing_and_prints_the_summary(self):
        with contextlib.ExitStack() as stack:
            model = stack.enter_context(patch(MODEL, return_value=answer()))
            sends = [stack.enter_context(patch(target, side_effect=AssertionError("sent"))) for target in SENDS]
            with self.assertNumQueries(0):
                text = self.call("--min-pass", "0")
        total = len(leadai_eval.SCENARIOS)
        # As live, what code settles (an opt-out, an automatic reply, a plain
        # acknowledgement, a deferral) never reaches the model.
        settled = [s.id for s in leadai_eval.SCENARIOS if leadai_eval.code_first(s) is not None]
        self.assertEqual(
            sorted(settled),
            [
                "away-message", "booked-emoji", "booked-ok-thanks", "defer-massage", "defer-message", "defer-with-time",
                "shops-a-yes-known", "shops-b-not-now", "shops-b-yes-known", "shops-b-yes-tap",
                # Chat 120's "No thankyou" (launch review issue 26): code's now, as "No thank you" always was.
                "shops-book-tap", "shops-licence-copy", "shops-licence-second-page",
                # Batch 2e: the mixed template's first answer, "Not now" and "Stop messages" are code's.
                "shops-mixed-not-now", "shops-mixed-stop", "shops-mixed-typed-yes", "shops-mixed-yes-1br-lead-arabic", "shops-mixed-yes-buyer-lead",
                "shops-mixed-yes-known-shop", "shops-mixed-yes-known-studio", "shops-mixed-yes-shop-lead", "shops-mixed-yes-studio-lead",
                "shops-mixed-yes-tap",
                "shops-no-thankyou-120", "shops-not-now", "shops-not-now-no", "shops-not-now-yes",
                "shops-other-types-tap", "shops-rented-no", "shops-rented-reach-out-63", "shops-rented-soft-no-63", "shops-spam", "shops-stop",
                "shops-track-shop-yes", "shops-type-tap",
                "shops-type-tap-again", "shops-yes-tap", "stop-all", "stop-arabic-after-english", "wrong-number",
            ],
        )
        # The fake answers in English, so a customer who types Arabic, Urdu or Devanagari script
        # gets the reply asked for once more in it (engine.ask_model, board T19); English letters
        # (scripts.LATIN) are what it answers in already.
        corrected = [
            s.id
            for s in leadai_eval.SCENARIOS
            if s.id not in settled and s.handed_over == "no"
            and leadai_eval.scripts.customer_script(leadai_eval.typed(s)) not in ("", leadai_eval.scripts.LATIN)
        ]
        self.assertEqual(
            sorted(corrected),
            [
                "lang-arabic", "lang-arabic-booking", "lang-arabic-yes", "lang-hindi-devanagari", "lang-urdu", "lang-urdu-after-english",
                "shops-arabic", "shops-track-room-and-hall-arabic", "shops-want-flat-arabic",
            ],
        )
        self.assertEqual(model.call_count, total - len(settled) + len(corrected))
        system, context = model.call_args_list[0].args[0][:2]
        self.assertEqual(system, {"role": "system", "content": prompt.system_prompt()})
        self.assertIn("NEW SINCE YOUR LAST REPLY", context["content"])
        self.assertEqual(model.call_args_list[0].kwargs["user"], leadai_eval.SAFETY_ID)
        for send in sends:
            send.assert_not_called()
        self.assertEqual(len(self.verdicts(text)), total)
        self.assertRegex(text, rf"\npassed \d+ of {total} \(\d+\.\d%\)\n")
        calls = total - len(settled) + len(corrected)
        self.assertIn(f"OpenAI: {calls} call(s) to gpt-4.1-mini, {calls * 1000:,} input and {calls * 100:,} output tokens", text)
        self.assertIn(f"estimated cost ${calls * (1000 * 0.40 + 100 * 1.60) / 1_000_000:.4f} at gpt-4.1-mini prices", text)
        for table in (LeadAiAppointment, LeadAiTurn, LeadAiAlert, LeadAiChatState):
            self.assertFalse(table.objects.exists(), table.__name__)

    def test_only_runs_the_matching_scenario(self):
        with patch(MODEL, return_value=booked("2026-10-13", "17:00")) as model:
            text = self.call("--only", "shop-tomorrow-5pm")
        self.assertEqual(model.call_count, 1)
        verdicts = self.verdicts(text)
        self.assertEqual(len(verdicts), 1)
        self.assertTrue(verdicts[0].startswith("PASS shop-tomorrow-5pm: "), verdicts[0])
        self.assertIn("action=confirm@office time=Tue 13 Oct 17:00", verdicts[0])
        self.assertIn("passed 1 of 1 (100.0%)", text)

        with patch(MODEL, return_value=booked("2026-10-13", "17:00")) as model:
            text = self.call("--only", "shop-tomorrow-5pm", "--repeat", "3")
        self.assertEqual([row.split(":")[0] for row in self.verdicts(text)], [f"PASS shop-tomorrow-5pm#{k}" for k in (1, 2, 3)])
        self.assertIn("passed 3 of 3 (100.0%)", text)

        self.call("--only", "no-such-scenario", exit_status=2)

    def test_a_wrong_answer_is_a_fail_with_its_reply_and_exit_status_1(self):
        with patch(MODEL, return_value=answer("Which time suits you tomorrow?", reply_en="")):
            text = self.call("--only", "shop-tomorrow-5pm", exit_status=1)
        verdict = self.verdicts(text)[0]
        self.assertTrue(verdict.startswith("FAIL shop-tomorrow-5pm: nothing booked (action none), expected Tue 13 Oct 17:00"), verdict)
        self.assertRegex(text, r"\n\s+reply:\s+Which time suits you tomorrow\?\n\s+reply_en:\s+-\n")
        self.assertIn("passed 0 of 1 (0.0%)", text)

        # Moving a booked meeting when the customer only said "see you at 5" is wrong...
        with patch(MODEL, return_value=booked("2026-10-13", "18:00")):
            text = self.call("--only", "booked-same-time", exit_status=1)
        verdict = self.verdicts(text)[0]
        self.assertIn("booked Tue 13 Oct 18:00 (reschedule), expected no booking", verdict)
        self.assertRegex(text, r"\n\s+goes out:\s+Done, Ahmed\. Your meeting is now on:")

        # ...while confirming the slot already booked changes nothing: the engine moves
        # nothing and sends no second confirmation (engine._said_again; batch 2b gate).
        with patch(MODEL, return_value=booked("2026-10-13", "17:00")):
            text = self.call("--only", "booked-same-time", "--show")
        verdict = self.verdicts(text)[0]
        self.assertTrue(verdict.startswith("PASS booked-same-time"), verdict)
        self.assertIn("action=none", verdict)
        self.assertNotIn("goes out:", text)
        self.assertNotIn("Your meeting is confirmed", text)

    def test_a_booking_the_system_had_to_correct_fails_a_strict_scenario(self):
        sunday = booked("2026-10-18", "17:00")
        fixed = answer("Our office is closed on Sunday. We're open Monday to Saturday. Would Monday at 5 PM work for you?")
        with patch(MODEL, side_effect=[sunday, fixed]) as model:
            text = self.call("--only", "shop-sunday", exit_status=1)
        self.assertEqual(model.call_count, 2)
        self.assertIn("closed on Sunday", model.call_args_list[1].args[0][-1]["content"])  # engine's own correction
        verdict = self.verdicts(text)[0]
        self.assertTrue(verdict.startswith("FAIL shop-sunday: the booking system had to correct it"), verdict)
        self.assertIn("(corrected once)", verdict)

    def test_a_price_in_the_reply_is_caught(self):
        price = answer("The rent is AED 45,000 a year. Would you like to visit our office?", invited=True)
        with patch(MODEL, return_value=price):
            text = self.call("--only", "shop-rent", "--show", exit_status=1)
        verdicts = self.verdicts(text)
        self.assertEqual(len(verdicts), 1)  # a whole id runs that scenario alone, not shop-rent-insisted too
        verdict = verdicts[0]
        self.assertTrue(verdict.startswith("FAIL shop-rent: "), verdict)
        self.assertIn("the reply filter removed: amount", verdict)
        self.assertIn("does not leave the rent to the specialist", verdict)
        self.assertIn("filtered:  amount", text)

    def test_openai_errors_fail_scenarios_and_three_in_a_row_stop_the_run(self):
        with patch(MODEL, side_effect=openai_client.AssistantError("http_429", "rate_limit_exceeded")) as model:
            text = self.call("--only", "shop-", "--min-pass", "0")
        self.assertEqual(model.call_count, 3)
        self.assertIn("FAIL shop-activity: OpenAI error http_429 (rate_limit_exceeded) | no answer", text)
        self.assertIn("Stopped: OpenAI failed 3 times in a row", text)
        planned = len([s for s in leadai_eval.SCENARIOS if "shop-" in s.id or "shop-" in s.title.lower()])
        self.assertIn(f"passed 0 of {planned} (0.0%)", text)

    @override_settings(LEADAI_OPENAI_API_KEY="")
    def test_without_the_key_it_refuses_to_start_but_still_lists(self):
        out = StringIO()
        with patch(MODEL) as model, self.assertRaises(CommandError) as raised:
            call_command("leadai_eval", stdout=out, stderr=StringIO(), no_color=True)
        self.assertEqual(raised.exception.returncode, 2)
        self.assertIn("LEADAI_OPENAI_API_KEY", str(raised.exception))
        model.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        listed = self.call("--list")
        self.assertIn("owner-viewing-slot", listed)
        self.assertIn(f"{len(leadai_eval.SCENARIOS)} scenario(s)", listed)

    def test_the_command_never_imports_the_send_services(self):
        tree = ast.parse(Path(leadai_eval.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
        self.assertFalse([name for name in names if "services" in name or "tasks" in name], names)
