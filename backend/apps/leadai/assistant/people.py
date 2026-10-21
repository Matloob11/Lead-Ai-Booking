"""When a person must act: handovers, calls, chases, must-answer questions and who hears of them.

Launch review 2026-10-15 (issues 3, 4, 14, 18 and 21; the reply cap's own part is caps.py):

- A call request (the model's handover ``call_requested``, or a call it recorded as tentative) is never
  answered with a promise of a call time on our agent's behalf: code writes the reply (``settle``), and
  says only that the request, with the time they gave, went to our agent (CALL_PASSED), or asks the
  time that suits them (CALL_ASK). Live, chat 88's "We can have a call at 11.30 - 12 PM" got "Our agent
  will call you today between 11:30 and 12:00", and nobody called. The handover alert and a timeline
  note on the lead carry the time asked (engine._handover_alert, tasks.record_crm_note "call").
- While a person has the chat (handed over), a message is answered by code alone (``quiet_reply``): a
  thanks or a goodbye gets nothing (chat 57's "its ok sir no prblm thankyou for ur response" got the
  holding line); a chase ("will i get any call??", "no one called", "hello?") gets an apology and an
  urgent alert to the team again (chat 88 got only the holding line, and nobody heard of it); a call
  time they give is passed on with its own alert; anything else the holding line, at most every two
  hours, in the shops playbook's own words ("our agent", never "our specialist").
- A shops customer's must-answer questions (a food business's gas, chimney, exhaust, grease trap, NOC,
  Municipality approval, drainage, power load; Ejari, the deposit, VAT, the total upfront amount, the
  fit-out period, the contract's terms) go to a person with the questions listed (a high alert, and
  one more if nobody answered in 30 office minutes), and the customer is told our agent answers them
  here before the visit, never "at the viewing" (chats 95, 91, 78). The chat goes on meanwhile: the
  line goes with the model's other words, and the assistant keeps sending what else they ask for
  (MUST_ANSWER_PAUSES False; batch 2d's review: the handover silenced the launch's hottest prospects).
  Commission alone is not one: Matloob's own line answers it (board Q24, MUST_ANSWER_COMMISSION); nor is
  a contract they want to sign ("I want to sign the contract today, when can I come?").
- A call is asked for in so many words: "call me" after a please, a yes or at the start of what they say,
  "call back" by them for us; never "Why did you call me?", "I'll call back later" or "call me Ahmed"
  (asks_for_call; batch 2d's review).
- No reply sends the customer to chase our colleague ("please contact Manhial", chat 114), and none
  promises a call nobody agreed; in a shops handover the reply asks nothing more (chat 105) and the
  holding line follows what is cut. An apology may repeat (filters.drop_repeats, engine.settle).
- A shops handover nobody from the team answered in 30 minutes of office time raises one more alert
  for that handover, to the chat's people and the Lead AI alert list (``escalate_waiting``), and so do
  must-answer questions nobody answered while the chat went on; never for a pause or a Broker someone set
  in Bitrix, a customer who opted out anywhere or said no since.
- Every handover, cap and escalation alert carries the customer's last words, the lead and where
  the chat is (``where_lines``).

The defaults are module constants, each a one-line change when Matloob decides otherwise.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from . import filters, hours, rules

logger = logging.getLogger(__name__)

# Defaults (Matloob's open decisions, synth.json decisions_for_matloob; one constant each) ------------------

# A handover with no reply from a person in this much office time (Mon-Sat 10:00-20:00, closed dates out)
# raises one more alert for it, to the chat's people and the Lead AI alert list (LISTED_KINDS).
ESCALATE_AFTER = dt.timedelta(minutes=30)
# Only in these playbooks: a general chat's owner sent the campaign and can open the chat.
ESCALATE_PLAYBOOKS = ("ic_shops",)
# A handover older than this is not escalated any more (a weekend's wait still is, on Monday morning).
ESCALATE_WITHIN = dt.timedelta(days=3)
ESCALATE_PAGE = 100
WAITING = "handover_waiting"
# While handed over, the chase, call and holding lines go at most this often (the alerts always go).
QUIET_LINE_EVERY = dt.timedelta(minutes=10)
# ... and a chase's urgent alert at most this often (review 2d: "Hello?", "??", "anyone there?" a minute apart were three
# high-priority alerts to each of the chat's people and 2311). A call's time given is alerted every time.
CHASE_ALERT_EVERY = QUIET_LINE_EVERY
# Commission alone is no must-answer question: Matloob's line answers it (board Q24, 2026-10-15).
MUST_ANSWER_COMMISSION = False
# Must-answer questions go to a person (a high alert to the chat's people and the Lead AI alert list, one more after
# ESCALATE_AFTER of office time if nobody answered), and the customer is told our agent answers them here before the
# visit; the chat itself is not paused: the assistant keeps sending the media, slots, bookings and price line they ask
# for (review 2d: the batch's handover silenced chats 91, 78 and 59, the launch's hottest prospects, for hours, as the
# reply cap had live). True hands the whole chat over instead, with the questions listed (the first default).
MUST_ANSWER_PAUSES = False
# The handover reason code gives must-answer questions (engine.HANDOVER_TEXT has its words).
MUST_ANSWER_REASON = "questions_for_agent"
# The alert kind of must-answer questions while the chat goes on (alerts.LISTED_KINDS; escalate_waiting reads it).
QUESTIONS = "questions"
# The model's handovers that only say a person must answer this (SHOPS_SYSTEM's MUST-ANSWER rule tells it to set
# legal_visa_licence_contract; a price detail insisted on; unclear): with must-answer questions found and no pause,
# none of them pauses the chat. Any other handover of the model's stays one (a photo sent, a tenancy problem, ...).
_MUST_ANSWER_COVERS = ("legal_visa_licence_contract", "price_or_details_insisted", "unclear")
# How much of their words a must-answer alert carries (chat 95 asked nine questions).
MUST_ANSWER_WORDS_MAX = 900
# How much of their last words a handover, cap or escalation alert carries.
WORDS_MAX = 300

# What code writes (answer["converted"]), in the customer's language --------------------------------------

HOLDING = "holding"
CHASE = "chase"
CALL_PASSED = "call_passed"
CALL_ASK = "call_ask"
MUST_ANSWER = "must_answer"
KINDS = (HOLDING, CHASE, CALL_PASSED, CALL_ASK, MUST_ANSWER)
# What quiet_reply makes of a message while a person has the chat.
QUIET_CLOSING = "closing"
QUIET_CHASE = CHASE
QUIET_CALL = "call"
QUIET_HOLDING = HOLDING

_SHOPS_LINES = {
    HOLDING: {
        "en": "Our agent has your message and will reply here.",
        "ar": "وصلت رسالتك إلى وكيلنا وسيرد عليك هنا.",
        "ur_latin": "Aap ka message hamare agent tak pahunch gaya hai, woh yahin jawab denge.",
        "ur": "آپ کا میسج ہمارے ایجنٹ تک پہنچ گیا ہے، وہ یہیں جواب دیں گے۔",
        "hi_latin": "Aapka message hamare agent tak pahunch gaya hai, woh yahin jawab denge.",
        "hi": "आपका मैसेज हमारे एजेंट तक पहुँच गया है, वो यहीं जवाब देंगे।",
    },
    CHASE: {
        "en": "Sorry for the wait. I've reminded our agent, who will reply to you here.",
        "ar": "نعتذر عن الانتظار. ذكّرت وكيلنا وسيرد عليك هنا.",
        "ur_latin": "Intezar ke liye maazrat. Main ne hamare agent ko yaad dila diya hai, woh yahin jawab denge.",
        "ur": "انتظار کے لیے معذرت۔ میں نے ہمارے ایجنٹ کو یاد دلا دیا ہے، وہ یہیں جواب دیں گے۔",
        "hi_latin": "Intezaar ke liye maafi. Maine hamare agent ko yaad dila diya hai, woh yahin jawab denge.",
        "hi": "इंतज़ार के लिए माफ़ी। मैंने हमारे एजेंट को याद दिला दिया है, वो यहीं जवाब देंगे।",
    },
    CALL_PASSED: {
        "en": "Thank you. I've passed your call request and the time you gave to our agent, who will confirm it with you here.",
        "ar": "شكراً لك. أرسلت طلب الاتصال والوقت الذي ذكرته إلى وكيلنا، وسيؤكده معك هنا.",
        "ur_latin": "Shukriya. Main ne aap ki call ki darkhwast aur aap ka bataya hua waqt hamare agent ko de diya hai, woh yahin aap se confirm kar lenge.",
        "ur": "شکریہ۔ میں نے آپ کی کال کی درخواست اور آپ کا بتایا ہوا وقت ہمارے ایجنٹ کو دے دیا ہے، وہ یہیں آپ سے کنفرم کر لیں گے۔",
        "hi_latin": "Shukriya. Maine aapki call ki request aur aapka bataya hua time hamare agent ko de diya hai, woh yahin aapse confirm kar lenge.",
        "hi": "शुक्रिया। मैंने आपकी कॉल की रिक्वेस्ट और आपका बताया हुआ समय हमारे एजेंट को दे दिया है, वो यहीं आपसे कन्फ़र्म कर लेंगे।",
    },
    CALL_ASK: {
        "en": "Sure, I'll pass your call request to our agent. What time suits you for the call?",
        "ar": "بالتأكيد، سأرسل طلب الاتصال إلى وكيلنا. ما الوقت المناسب لك للاتصال؟",
        "ur_latin": "Zaroor, main aap ki call ki darkhwast hamare agent ko de deta hoon. Call ke liye aap ko kaunsa waqt theek rahega?",
        "ur": "ضرور، میں آپ کی کال کی درخواست ہمارے ایجنٹ کو دے دیتا ہوں۔ کال کے لیے آپ کو کون سا وقت ٹھیک رہے گا؟",
        "hi_latin": "Zaroor, main aapki call ki request hamare agent ko de deta hoon. Call ke liye aapko kaunsa time theek rahega?",
        "hi": "ज़रूर, मैं आपकी कॉल की रिक्वेस्ट हमारे एजेंट को दे देता हूँ। कॉल के लिए आपको कौन सा समय ठीक रहेगा?",
    },
    MUST_ANSWER: {
        "en": "Thank you, these are important questions. Our agent will answer them for you here before the visit.",
        "ar": "شكراً لك، هذه أسئلة مهمة. سيجيب عنها وكيلنا هنا قبل الزيارة.",
        "ur_latin": "Shukriya, yeh aham sawalat hain. Hamare agent visit se pehle yahin aap ko in ke jawab denge.",
        "ur": "شکریہ، یہ اہم سوالات ہیں۔ ہمارے ایجنٹ وزٹ سے پہلے یہیں آپ کو ان کے جواب دیں گے۔",
        "hi_latin": "Shukriya, yeh zaroori sawaal hain. Hamare agent visit se pehle yahin aapko inke jawab denge.",
        "hi": "शुक्रिया, ये ज़रूरी सवाल हैं। हमारे एजेंट विज़िट से पहले यहीं आपको इनके जवाब देंगे।",
    },
}
# A general chat's own: "our specialist", as every line of that playbook says (its holding line is rules').
_GENERAL_LINES = {
    CHASE: {
        "en": "Sorry for the wait. I've reminded our specialist, who will reply to you here.",
        "ar": "نعتذر عن الانتظار. ذكّرت المختص لدينا وسيرد عليك هنا.",
        "ur_latin": "Intezar ke liye maazrat. Main ne hamare specialist ko yaad dila diya hai, woh yahin jawab denge.",
        "ur": "انتظار کے لیے معذرت۔ میں نے ہمارے اسپیشلسٹ کو یاد دلا دیا ہے، وہ یہیں جواب دیں گے۔",
        "hi_latin": "Intezaar ke liye maafi. Maine hamare specialist ko yaad dila diya hai, woh yahin jawab denge.",
        "hi": "इंतज़ार के लिए माफ़ी। मैंने हमारे स्पेशलिस्ट को याद दिला दिया है, वो यहीं जवाब देंगे।",
    },
    CALL_PASSED: {
        "en": "Thank you. I've passed your call request and the time you gave to our specialist, who will confirm it with you here.",
        "ar": "شكراً لك. أرسلت طلب الاتصال والوقت الذي ذكرته إلى المختص لدينا، وسيؤكده معك هنا.",
        "ur_latin": "Shukriya. Main ne aap ki call ki darkhwast aur aap ka bataya hua waqt hamare specialist ko de diya hai, woh yahin aap se confirm kar lenge.",
        "ur": "شکریہ۔ میں نے آپ کی کال کی درخواست اور آپ کا بتایا ہوا وقت ہمارے اسپیشلسٹ کو دے دیا ہے، وہ یہیں آپ سے کنفرم کر لیں گے۔",
        "hi_latin": "Shukriya. Maine aapki call ki request aur aapka bataya hua time hamare specialist ko de diya hai, woh yahin aapse confirm kar lenge.",
        "hi": "शुक्रिया। मैंने आपकी कॉल की रिक्वेस्ट और आपका बताया हुआ समय हमारे स्पेशलिस्ट को दे दिया है, वो यहीं आपसे कन्फ़र्म कर लेंगे।",
    },
    CALL_ASK: {
        "en": "Sure, I'll pass your call request to our specialist. What time suits you for the call?",
        "ar": "بالتأكيد، سأرسل طلب الاتصال إلى المختص لدينا. ما الوقت المناسب لك للاتصال؟",
        "ur_latin": "Zaroor, main aap ki call ki darkhwast hamare specialist ko de deta hoon. Call ke liye aap ko kaunsa waqt theek rahega?",
        "ur": "ضرور، میں آپ کی کال کی درخواست ہمارے اسپیشلسٹ کو دے دیتا ہوں۔ کال کے لیے آپ کو کون سا وقت ٹھیک رہے گا؟",
        "hi_latin": "Zaroor, main aapki call ki request hamare specialist ko de deta hoon. Call ke liye aapko kaunsa time theek rahega?",
        "hi": "ज़रूर, मैं आपकी कॉल की रिक्वेस्ट हमारे स्पेशलिस्ट को दे देता हूँ। कॉल के लिए आपको कौन सा समय ठीक रहेगा?",
    },
}
# Every line ends a handover's reply (it says a person replies here): code keeps it out of the model's cuts.
ALL_LINES = frozenset(
    line for table in (*_SHOPS_LINES.values(), *_GENERAL_LINES.values(), rules.LINES["holding"]) for line in table.values()
)


def line(kind: str, language: str, *, shops: bool) -> str:
    """Code's line ``kind`` in the customer's language: a shops chat's own words ("our agent"), a general
    chat's ("our specialist"; its holding line is rules.LINES["holding"]). The shops-only must-answer
    line is the shops one everywhere."""
    if kind == HOLDING and not shops:
        return rules.line("holding", language)
    table = (_SHOPS_LINES if shops or kind == MUST_ANSWER else _GENERAL_LINES)[kind]
    return table.get(language) or table["en"]


# Reading the customer -------------------------------------------------------------------------------------

# A thanks or a goodbye, nothing more (chat 57: "its ok sir no prblm thankyou for ur response"): read word by
# word after rules.normalize_text, at least one of _CLOSING_CORE (or "no problem"), every other word one of
# _CLOSING_WORDS. Longer than rules.is_acknowledgement's six words, and only while a person has the chat.
_CLOSING_CORE = frozenset(
    """
    thanks thank thankyou thanku thnx thanx thnks thx tnx ty tq tqsm shukriya shukria shukran jazakallah jazakallahu
    jazak bye byee bye-bye goodbye tc regards cheers appreciated appreciate dhanyavaad dhanyawad meherbani mehrbani
    شكرا شكراً مشكور مشكورين تسلم يعطيك العافية جزاك جزيلا جزيلاً سلامة شکریہ شکريہ مہربانی جزاک धन्यवाद शुक्रिया
    """.split()
)
_CLOSING_WORDS = _CLOSING_CORE | frozenset(
    """
    ok okay okk okey k kk alright allright fine good great nice sure noted done well
    its it is s that this no problem prblm prob probs problm prblem issue issues worries worry
    you u ur your yours for the a an all of to so very much lot alot really again too kind kindly
    response reply replying help helping time info information support assistance patience update message details
    sir sirr madam maam mam dear bro brother bhai bhaiya ji jee yaar habibi akhi boss friend
    have take care day evening night weekend ahead nice wonderful blessed khair allah
    and then later soon will wait waiting see
    theek thik hai hain koi baat nahi nahin achha acha accha bohot bahut bahot
    ما في مشكلة لا بأس اوكي أوكي تمام طيب خير الله ويعطيك العافيه كثير
    ٹھیک ہے کوئی بات نہیں بہت اچھا جی
    ठीक है कोई बात नहीं बहुत अच्छा जी
    """.split()
)
CLOSING_WORDS_MAX = 16


def is_closing(text: str) -> bool:
    """A message that only thanks, says goodbye or "no problem" ("ok thank you so much", "its ok sir no prblm
    thankyou for ur response", "شكرا جزيلا"): while a person has the chat, it gets nothing (quiet_reply). A
    question, a time, "but", "call", "when" or any other word is more than that."""
    raw = str(text or "")
    if rules.asks_question(raw):
        return False
    words = rules.normalize_text(raw).split()
    if not words or len(words) > CLOSING_WORDS_MAX or any(word not in _CLOSING_WORDS for word in words):
        return False
    joined = f" {' '.join(words)} "
    agreed = words[0] in ("ok", "okay", "okk", "okey", "sure", "fine", "alright", "allright", "theek", "thik")
    if " will wait " in joined or joined.endswith(" will wait "):
        return agreed  # "ok, will wait" closes; "I will wait" alone may open a chase ("will wait for the call?")
    return any(word in _CLOSING_CORE for word in words) or bool(re.search(r" no (?:problem|prblm|prob|probs|problm|prblem|issue|worries) ", joined))


# A chase while a person has the chat: they are still waiting for our reply or a call (chat 88: "will i get any
# call??"). In English, Roman Urdu/Hindi, Arabic, Urdu and Hindi script.
_CHASE = re.compile(
    r"\b(?:will|shall|would|do|did|can|could|should)\s+(?:i|we|u|you)\s+(?:\w+\s+){0,2}?(?:get|receive|recieve)\b[^.!?\n]{0,15}?\b(?:call|reply|response|answer)\b"
    r"|\b(?:no\s*one|noone|nobody|no\s*body|none)\b[^.!?\n]{0,20}?\b(?:call(?:ed|s)?|repl(?:y|ied|ies)|respond(?:ed|s)?|answer(?:ed|s)?|contact(?:ed)?|came|come|wrote|texted|messaged)\b"
    r"|\b(?:still|i\s*am|i'?m|im|we\s*are|we'?re)\s+waiting\b|\bwaiting\s+for\s+(?:your|ur|the|a|an|my)?\s*(?:call|reply|response|answer|agent|update|message)"
    r"|\bany\s+(?:update|updates|news|reply|response|feedback)\b"
    r"|\b(?:are\s+you|r\s+u|ru|is\s+(?:any\s*one|anybody|someone|somebody)|any\s*one|anybody)\s+(?:there|here|available|online|replying|answering)\b"
    r"|\b(?:when|why|kab|kyun|kyon)\b[^.!?\n]{0,25}?\b(?:call(?:ing)?|reply|replying|respond|responding|answer|contact|ring)\b"
    r"|\b(?:no|not\s+(?:a|any)|not)\s+(?:call|reply|response|answer)\s+(?:yet|so\s+far|received|till\s+now|until\s+now)\b"
    r"|\b(?:no\s+(?:call|reply|response))\s*[?؟!]"
    r"|\byou\s+(?:said|told|promised)\b[^.!?\n]{0,30}?\b(?:call|reply|contact|message)\b"
    r"|\bwhere\s+is\s+(?:the|my|your|ur)?\s*(?:call|agent|reply|response)\b"
    r"|^\W*(?:hello+|helo+|hallo+|hi+|hey+|salam|assalam\w*)\s*[?؟]+\W*$"
    r"|^\W*[?؟]{2,}\W*$"
    r"|\bcall\s+(?:kab|nahi|nhi|nahin|nai)\b|\bkab\s+(?:call|phone|jawab|reply|rabta)\b|\b(?:koi|kisi\s+ne)\s+(?:call|phone|jawab|reply|rabta)\b"
    r"|\babhi\s+tak\b|\bjawab\s+(?:do|dein|den|nahi|nhi|nahin)\b|\breply\s+(?:karo|kro|kar\s+do|nahi|nhi|nahin)\b|\bintez?aa?r\s+(?:kar|kr)\s*(?:raha|rahi|rahe|rha|rhi)\b"
    r"|(?:متى|ليش|لماذا|ليه)\s*(?:\S+\s+){0,3}?(?:تتصل|تتصلون|اتصال|الاتصال|ترد|تردون|الرد|يرد|يتصل)"
    r"|(?:ما|لم)\s*(?:حد|أحد|احد)?\s*(?:اتصل|يتصل|رد|يرد|تواصل)|وينكم|وين\s*الرد|(?:في|فيه)\s*(?:أحد|احد)|(?:أنا|انا)\s*(?:أنتظر|انتظر|بانتظار)|لا\s*يوجد\s*رد"
    r"|ابھی\s*تک|کال\s*کب|کب\s*کال|کوئی\s*(?:کال|جواب)|جواب\s*(?:دیں|نہیں)|انتظار\s*کر"
    r"|अभी\s*तक|कॉल\s*कब|कब\s*कॉल|कोई\s*(?:कॉल|जवाब)|जवाब\s*(?:दो|दें|नहीं)|इंतज़ार\s*कर|इंतजार\s*कर",
    re.IGNORECASE,
)


def is_chase(text: str) -> bool:
    """They are still waiting for us, in any words: "will i get any call??", "no one called", "still waiting",
    "any update?", "hello?", "??", "koi call nahi aya", "ما احد اتصل", "ابھی تک کال نہیں آئی". Read only while
    a person has the chat (quiet_reply): an apology and an urgent alert, never the holding line again."""
    return bool(_CHASE.search(" ".join(str(text or "").replace("’", "'").split())))


def call_hour(said: str, now=None) -> bool:
    """Their words name an hour (for a call): "at 11.30 - 12 PM", "5 baje", "in an hour"; a day alone is no time."""
    words = str(said or "")
    return bool(hours.said_times(words) or hours.marks_hour(words) or hours.hours_ahead(words))


# They ask us for a call ("Please call me, I am driving", "We can have a call at 11.30 - 12 PM", "call kar lo",
# "اتصل بي", "کال کریں"), never "do not call me" nor "I will call you". "call me" and "call back" are read on their
# own (_asks_call_me, _asks_call_back): review 2d found "Why did you call me?", "I'll call back later" and "you can
# call me Ahmed" handed over as call requests in every playbook.
_CALL_REQUEST = re.compile(
    r"\b(?:give|gimme)\s+(?:me\s+|us\s+)?a\s+(?:call|ring)\b"
    r"|\b(?:can|could|would|will)\s+(?:you|u|someone|somebody|anyone|your\s+(?:agent|team|specialist))\s+(?:please\s+|pls\s+|kindly\s+)?(?:call|ring|phone)\b"
    r"|\b(?:pls|please|plz|kindly)\s+(?:call|ring|phone)\b"
    r"|\b(?:have|need|want|prefer|like|do|arrange|schedule|set\s+up)\s+(?:a\s+|an\s+)?(?:quick\s+|short\s+)?(?:call|phone\s+call|voice\s+call)\b"
    # "Urgent for call", "for a call please", "call please", "need call" (the first mixed campaign, 2026-10-19, chat 50005:
    # "Urgent ‼️ for call" got the studio price and nobody was told).
    r"|\b(?:urgent|urgently|asap)\b[^.?!]{0,20}?\b(?:for\s+(?:a\s+)?)?call\b|\bfor\s+(?:a\s+)?(?:quick\s+)?call\s*(?:please|pls|plz)?\s*$"
    r"|\bcall\s+(?:please|pls|plz)\s*$|\bneed\s+call\b"
    r"|\bcall\s+(?:kar(?:o|en|ein|lo|do|dein|na|iye|ein\s+ge)?|krna|kr\s+do|kr\s+lo)\b|\bmujhe\s+(?:call|phone)\b|\bphone\s+(?:kar|karo|karein|kr)\b"
    r"|اتصل\s*(?:بي|علي|عليا|فيني)|اتصلوا|كلمني|ممكن\s*(?:اتصال|مكالمة|تتصل)|(?:أريد|اريد|ابغى|أبغى)\s*(?:اتصال|مكالمة)"
    r"|کال\s*(?:کریں|کرو|کر\s*دیں|کر\s*لیں)|مجھے\s*کال|फ़ोन\s*(?:करें|करो)|फोन\s*(?:करें|करो)|कॉल\s*(?:करें|करो|कर\s*दें|कर\s*लें)|मुझे\s*कॉल",
    re.IGNORECASE,
)
_NO_CALL = re.compile(
    r"\b(?:don'?t|do\s+not|dont|never|no\s+need\s+to|not)\s+(?:\w+\s+){0,3}(?:call|ring|phone)\b|\b(?:no|not\s+a)\s+calls?\b|\bcall\s+(?:mat|na|nahi|nhi)\b"
    r"|لا\s*(?:تتصل|تتصلوا)|کال\s*(?:مت|نہ)|कॉल\s*(?:मत|न)",
    re.IGNORECASE,
)
# "call me", "call us back", "ring him": a request when it opens what they say, after a please or a yes ("ok call me at
# 5"), never after a subject or a question word ("Why did you call me?", "you call me yesterday", "Someone tried to
# call me"), nor naming them ("you can call me Ahmed").
_CALL_ME = re.compile(r"\b(?:call|ring|phone)\s+(?:me|us|him|her)\b", re.IGNORECASE)
# "call back", "ring back", "phone back": a request unless they will do it themselves ("I'll call back later", "will call
# back in 5 min", "let me phone back").
_CALL_BACK = re.compile(r"\b(?:call|ring|phone)\s+back\b", re.IGNORECASE)
_CLAUSE_START = re.compile(r"[.!?؟,;:\n]|\b(?:but|and|so|then)\b", re.IGNORECASE)
# What may come right before a request for a call: a please or a yes ("ok call me at 5", "flat please call me").
_ASKING_FIRST = re.compile(
    r"\b(?:please|pls|plz|kindly|just|ok|okay|sure|yes|yeah|ji|haan|then|so|sir|bro|madam|urgent|urgently|asap)\s*$", re.IGNORECASE
)
# ... and someone asked to call them ("I need you to call me", "ask someone to call me back").
_ASKED_TO = re.compile(r"\b(?:need|want|ask|tell|get)\s+(?:you|u|someone|somebody|anyone|him|her|them|your\s+\w+)?\s*to\s*$", re.IGNORECASE)
# The words right before "call me" that make it no request: a subject or a question ("why did you", "you", "tried to").
_NOT_ASKING = frozenset(
    "did do does didnt didn't why who when whom you u he she they someone somebody anyone tried trying try to i we i'll ill we'll "
    "i'm im will shall gonna can may might could would used never not dont don't".split()
)
_A_NAME_NEXT = re.compile(r"\s+[A-Z][a-z]+\b(?<!Monday)(?<!Tuesday)(?<!Wednesday)(?<!Thursday)(?<!Friday)(?<!Saturday)(?<!Sunday)")


def _clause_before(words: str, start: int) -> str:
    """The words of the clause before ``start`` (from the last stop, comma or "but"/"and" before it)."""
    before = words[:start]
    cut = [match.end() for match in _CLAUSE_START.finditer(before)]
    return before[cut[-1] :] if cut else before


def _asks_call_me(words: str) -> bool:
    for match in _CALL_ME.finditer(words):
        before = _clause_before(words, match.start()).strip()
        if _A_NAME_NEXT.match(words, match.end()) and re.search(r"\b(?:can|may|just)\s*$", before, re.IGNORECASE):
            continue  # "you can call me Ahmed": their name
        last = [word.lower().strip("'") for word in before.split()[-2:]]
        if not before or _ASKING_FIRST.search(before) or _ASKED_TO.search(before) or not any(word in _NOT_ASKING for word in last):
            return True
    return False


def _asks_call_back(words: str) -> bool:
    for match in _CALL_BACK.finditer(words):
        before = _clause_before(words, match.start())
        if not re.search(r"\b(?:i|we|i'?ll|we'?ll|i'?m|will|shall|gonna|going\s+to|let\s+me|can)\b", before, re.IGNORECASE):
            return True
    return False
# A call spoken of at all (a model's call request is read only with one of these in their words).
_CALL_WORD = re.compile(r"\b(?:call|calls|calling|ring|phone)\b|اتصل|اتصال|مكالمة|كلمني|کال|فون|कॉल|फ़ोन|फोन", re.IGNORECASE)
# A visit spoken of ("I can come at 5", "kal office aa jaunga"): an hour with it is the visit's, not a call's.
_VISIT = re.compile(
    r"\b(?:visit|come|coming|meet|office|viewing|appointment|book)\b|\baa\s*(?:jaunga|jaoonga|jaungi|sakta|sakti|jayenge|jaenge)\b"
    r"|زيارة|أزور|ازور|أجي|اجي|موعد|معاينة|آؤں|آ\s*جاؤں|آ\s*جاؤں\s*گا|आऊँ|आ\s*जाऊँ|आ\s*जाऊंगा",
    re.IGNORECASE,
)


def asks_for_call(said: str) -> bool:
    """Their words ask us for a call, and do not refuse one."""
    words = " ".join(str(said or "").replace("’", "'").split())
    asked = bool(_CALL_REQUEST.search(words)) or _asks_call_me(words) or _asks_call_back(words)
    return asked and not _NO_CALL.search(words)


# Reading our reply ----------------------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?؟۔।])\s+|\n+")
# We promise a call on a person's behalf ("Our agent will call you today between 11:30 and 12:00", "we'll give
# you a call", "you will receive a call shortly", "aap ko call karenge", "سيتصل بك", "کال کریں گے").
_PROMISES_CALL = re.compile(
    r"\b(?:will|shall|'ll|ll|going\s+to|gonna|would)\s+(?:\w+\s+){0,2}?(?:call|ring|phone)\s+(?:you|u|back)\b"
    r"|\b(?:will|shall|'ll|going\s+to)\s+(?:give\s+you|arrange|schedule|set\s+up)\s+(?:a\s+)?(?:quick\s+)?(?:call|phone\s+call)\b"
    r"|\byou\s+(?:will|'ll)\s+(?:get|receive|have)\s+(?:a\s+)?(?:call|phone\s+call)\b|\bexpect\s+(?:a|our)\s+call\b"
    r"|\bcall\s+(?:kar(?:enge|ega|egi|e\s+ga|en\s+ge|\s+lenge|\s+lega)|karwa\s+denge)\b"
    r"|(?:سيتصل|سنتصل|راح\s*يتصل|بيتصل)\s*(?:بك|فيك|عليك)?"
    r"|کال\s*(?:کریں\s*گے|کرے\s*گا|کریں\s*گی)|कॉल\s*(?:करेंगे|करेगा|करेगी)",
    re.IGNORECASE,
)
# We send them to a colleague or the office themselves ("For apartments, please contact Manhial as you mentioned",
# "you can reach our agent", "kindly call our office", "یہاں رابطہ کریں"): our colleague replies here instead.
# Our side, or a person by name (a capital letter: "Manhial"); the words around it are read in any case.
_PERSON = (
    r"(?i:our\s+|the\s+|your\s+|my\s+)?(?:(?i:agents?|colleagues?|specialist|team|office|manager|sales|leasing|broker|consultant|him|her|them)"
    r"|[A-Z][a-z]{2,})"
)
_SENDS_TO_COLLEAGUE = re.compile(
    rf"(?i:\b(?:please|pls|plz|kindly|you\s+(?:can|may|could|should|might|will\s+need\s+to|need\s+to)|feel\s+free\s+to|do|just|best\s+to)\s+(?:directly\s+)?"
    rf"(?:contact|call|reach\s+out\s+to|reach|message|text|whatsapp|email|e-mail|get\s+in\s+touch\s+with|speak\s+(?:to|with)|talk\s+(?:to|with)|connect\s+with|follow\s+up\s+with)\s+(?:directly\s+)?){_PERSON}\b"
    r"|(?i:\b(?:se|sey)\s+(?:rabta|raabta|contact|baat)\s+(?:karein|karen|kar\s+lein|kar\s+len|karo|kar\s+lo|kijiye|kariye)\b)"
    r"|(?:يرجى|يمكنك|الرجاء)\s+(?:التواصل|الاتصال)\s+(?:مع|ب)|(?:تواصل|اتصل|راسل)\s+(?:مع\s+)?(?:الوكيل|وكيلنا|المختص|فريق|المكتب|زميل)"
    r"|سے\s+رابطہ\s+(?:کریں|کر\s+لیں)|से\s+संपर्क\s+(?:करें|कर\s+लें|कीजिए)",
)
# Our words already say a colleague replies to them here ("Our agent will reply to you here").
_COLLEAGUE_REPLIES = re.compile(
    r"\b(?:agent|agents|specialist|colleague|team)\b[^.?!]{0,40}?\b(?:reply|replies|respond|answer|get\s+back|confirm)\b",
    re.IGNORECASE,
)
_APOLOGY = re.compile(
    r"\b(?:sorry|apologi[sz]e|apologies|pardon)\b|\b(?:maaf|maafi|maafi|maazrat|mazrat|muafi|muaafi|maazarat)\b"
    r"|نعتذر|أعتذر|اعتذر|آسف|اسف|عذرا|عذراً|معذرة|معذرت|معافی|माफ़|माफ|क्षमा",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(str(text or "")) if part.strip()]


def promises_call(sentence: str) -> bool:
    """The sentence promises a call on our side's behalf, with or without a time."""
    return bool(_PROMISES_CALL.search(" ".join(str(sentence or "").replace("’", "'").split())))


def sends_to_colleague(sentence: str) -> bool:
    """The sentence tells the customer to contact, call or message someone of ours themselves."""
    return bool(_SENDS_TO_COLLEAGUE.search(" ".join(str(sentence or "").replace("’", "'").split())))


def is_apology(sentence: str) -> bool:
    """The sentence says sorry: it may repeat in a chat (filters.drop_repeats keeps it; chat 114 lost its "Sorry")."""
    return bool(_APOLOGY.search(str(sentence or "")))


def says_colleague_replies(text: str) -> bool:
    """A sentence of these words says a colleague will reply to them ("Our specialist will reply here to assist you
    further", "Our team will reply here shortly"): true only of a chat handed to a person, whom the handover alerts
    (engine.settle_handover keeps the model's handover for it)."""
    return any(_COLLEAGUE_REPLIES.search(sentence) for sentence in sentences(text))


# Must-answer questions (shops) -------------------------------------------------------------------------

# (topic, pattern): what a food business needs to know before any unit can work at all, and the contract and
# the money; asked about (a question mark, or a word that asks), never mentioned in passing.
_TOPICS = (
    ("gas line", r"\bgas\b|غاز|گیس|गैस"),
    ("chimney", r"\bchimn(?:e?y|ies|eys)\b|\bchimeny\b|مدخنة|چمنی|चिमनी"),
    ("exhaust or ventilation", r"\bexhaust\b|\bventilat\w*|\bkitchen\s+hood\b|\bhood\s+(?:system|duct)\b|\bfume\b|شفاط|تهوية|ایگزاسٹ|वेंटिलेशन"),
    ("grease trap", r"\bgrease\b|مصيدة\s*(?:ال)?دهون|گریس|ग्रीस"),
    ("NOC", r"\bN\.?\s?O\.?\s?C\.?\b|\bno\s+objection\b|عدم\s*ممانعة|عدم\s*الممانعة"),
    ("Municipality approval", r"\bmunicipal\w*|\bDM\s+(?:approval|permit|licen[cs]e)\b|\bfood\s+(?:safety|control|establishment|permit)\b|بلدية|میونسپلٹی|नगरपालिका"),
    ("drainage or water", r"\bdrain\w*|\bwater\s+(?:supply|line|connection|point|inlet)\b|\bsewer\w*|\bplumbing\b|صرف\s*صحي|مياه|نکاسی|ड्रेनेज"),
    (
        "power load",
        r"\b(?:power|electric(?:al|ity)?|dewa)\s+(?:load|capacity|supply|connection|meter)\b|\b\d*\s*kw\b|\bkilowatt\w*|\b(?:three|3)[\s-]phase\b"
        r"|\bload\b[^.?!\n]{0,20}\b(?:power|electric\w*|kw)\b|حمل\s*كهرب|بجلی\s*کا\s*لوڈ|बिजली\s*(?:का\s*)?लोड",
    ),
    ("Ejari", r"\bejari\b|إيجاري|ايجاري|ایجاری|एजारी"),
    # "rent security" is the deposit (launch chat 59: "And give me full details including rent security").
    ("deposit", r"\bdeposit\w*|\bsecurity\s+(?:amount|cheque|check|deposit|money|fee|fees)\b|\brent\s+security\b|تأمين|وديعة|ڈپازٹ|ڈیپازٹ|डिपॉज़िट|डिपॉजिट"),
    ("VAT", r"\bvat\b|ضريبة|ویٹ|वैट"),
    (
        "total upfront amount",
        r"\b(?:total|full|complete|whole|overall|entire)\s+(?:upfront|up-front|up\s+front|amount|cost|costs|payment|price|charges)\b"
        r"|\bup\s*-?\s*front\b|\bhow\s+much\s+(?:in\s+total|total|altogether|all\s+together|to\s+pay\s+(?:first|upfront|initially))\b"
        r"|\b(?:all|other|any\s+other|extra|additional|hidden)\s+(?:the\s+)?(?:fees|charges|costs)\b|\bbreak\s*-?\s*down\b|\bcomputation\b|\bcalculation\b",
    ),
    ("fit-out period", r"\bfit[\s-]?out\s+(?:period|time|months?|days?|weeks?)\b|\brent[\s-]?free\b|\bgrace\s+period\b"),
    ("contract", r"\bcontract\w*|\btenancy\s+(?:agreement|contract|terms)\b|\blease\s+(?:agreement|terms|contract)\b|عقد|کنٹریکٹ|معاہدہ|अनुबंध|कॉन्ट्रैक्ट"),
)
_COMMISSION = ("commission", r"\bcommission\w*|\bagency\s+fee\w*|\bbrokerage\b|عمولة|کمیشن|कमीशन")
# A clause that asks: a question mark, or a word that asks or asks for ("can you", "is there", "provide", "tell me").
_ASKS = re.compile(
    r"[?؟]|\b(?:is|are|was|were|will|would|can|could|do|does|did|how|what|which|when|where|who|whether|any|provide|available|"
    r"allowed|possible|tell|share|confirm|know|need\s+to\s+know|let\s+me\s+know|give|send|explain|kya|kia|milega|milegi|hoga|hogi|batao|bataiye)\b"
    r"|هل|كم|متى|ممكن|يوجد|أريد\s*أعرف|کیا|کتنا|کتنی|کب|بتائیں|क्या|कितना|कितनी|कब|बताइए|बताएं",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"(?<=[.!?؟۔।])\s+|\n+|(?<=\d)\.\s+|;\s*")
# The contract asked to be done, not asked about ("I want to sign the contract today, when can I come?", "Can I do the
# contract this week?"): a customer ready to book, never a must-answer question (review 2d) ...
_CONTRACT_DONE = re.compile(
    r"\b(?:sign|signing|do|doing|make|making|start|starting|finali[sz]e|finish|complete|close|ready\s+(?:to|for))\b[^.?!\n]{0,20}?\bcontract"
    r"|\bcontract\b[^.?!\n]{0,20}?\b(?:today|tomorrow|this\s+week|now|asap)\b",
    re.IGNORECASE,
)
# ... unless the clause asks about its terms too ("Can I sign the contract for 2 years?", "can you send the contract copy?").
_CONTRACT_TERMS = re.compile(
    r"\bhow\s+long\b|\bduration\b|\bperiod\b|\byears?\b|\byearly\b|\bannual\w*|\bmonths?\b|\brenew\w*|\bnotice\b|\bterms?\b|\bconditions?\b"
    r"|\bclauses?\b|\bbreak\b|\bcancel\w*|\bexit\b|\bminimum\b|\bcopy\b|\bdraft\b|\bsample\b|\bsend\b|\bshare\b|\bdetails?\b|\bsaal\b|\bmahine\b"
    r"|مدة|سنة|سنوات|شروط|تجديد|مدت|سال|शर्त|साल|अवधि",
    re.IGNORECASE,
)


def _topics() -> tuple:
    return (*_TOPICS, _COMMISSION) if MUST_ANSWER_COMMISSION else _TOPICS


def asked_topics(texts) -> list[tuple[str, list[str]]]:
    """Each clause of their words that asks a must-answer topic, with its topics in the build pack's order: what
    must_answer reads, a clause at a time (crm_facts notes the clauses, so none of their questions is lost)."""
    topics = _topics()
    out: list[tuple[str, list[str]]] = []
    for text in texts or ():
        for clause in _CLAUSE.split(str(text or "")):
            clause = clause.strip()
            if not clause or not _ASKS.search(clause):
                continue
            found = []
            for topic, pattern in topics:
                if re.search(pattern, clause, re.IGNORECASE):
                    if topic == "contract" and _CONTRACT_DONE.search(clause) and not _CONTRACT_TERMS.search(clause):
                        continue  # they want to sign or book, and ask nothing about its terms
                    found.append(topic)
            if found:
                out.append((clause, found))
    return out


def names_topic(text: str, topic: str) -> bool:
    """The text names this must-answer topic ("gas line", "Ejari", ...), in its own pattern's words."""
    pattern = dict(_topics()).get(topic)
    return bool(pattern and re.search(pattern, str(text or ""), re.IGNORECASE))


def must_answer(texts) -> list[str]:
    """The must-answer topics their words ask about, in the build pack's order ([] when none): a food
    business's gas, chimney, exhaust, grease trap, NOC, Municipality approval, drainage and power load, and
    Ejari, the deposit, VAT, the total upfront amount, the fit-out period and the contract. Commission alone
    is Matloob's own line (board Q24), unless MUST_ANSWER_COMMISSION. A clause must ask ("is there available
    gas line and chimney?", "can u give me the detai computation"); a mention in passing ("I had a gas
    station before") asks nothing."""
    found: list[str] = []
    for _, topics in asked_topics(texts):
        found += [topic for topic in topics if topic not in found]
    order = [topic for topic, _ in _topics()]
    return sorted(found, key=order.index)


# The model's words that leave a question to a person or the viewing (the build pack's "Good question — I'll have our
# agent confirm that for you at the viewing.", "our agent will go through the deposit with you at our office"): code's
# must-answer line says it instead.
_LEFT_TO_A_PERSON = re.compile(
    r"\b(?:agent|agents|specialist|colleague|team)\b[^.?!]{0,60}?\b(?:confirm|check|tell|share|explain|answer|clarify|go\s+through|discuss)"
    r"|\bat\s+the\s+(?:viewing|visit)\b|\bat\s+(?:our|the)\s+office\b|\bwhen\s+you\s+(?:visit|come)\b|\bviewing\s+(?:par|pe|mein|ke\s+waqt)\b"
    r"|\bagent\b[^.?!]{0,40}\b(?:batayenge|bata\s+denge|confirm\s+kar|tasdeeq|pushti|jawab)"
    r"|عند\s+المعاينة|وكيلنا\s+(?:سيؤكد|يؤكد|سيوضح|سيجيب)|ایجنٹ[^۔?؟]{0,40}(?:بتائیں|کنفرم|تصدیق|جواب)|एजेंट[^।?]{0,40}(?:बताएँगे|कन्फ़र्म|पुष्टि|जवाब)",
    re.IGNORECASE,
)
# A thanks for their questions: code's line thanks them.
_THANKS_FIRST = re.compile(r"^\W*(?:thanks|thank\s+you|thankyou|shukriya|shukria|شكرا|شكراً|شکریہ|शुक्रिया|धन्यवाद)\b", re.IGNORECASE)
# Our agent's drive to the shops: part of an invitation, nothing without one.
_DRIVE = re.compile(r"\bdrive\s+you\b|\bgaari\s+mein\b|بالسيارة|گاڑی\s+میں|गाड़ी\s+में", re.IGNORECASE)


def must_answer_kept(reply: str) -> str:
    """The model's words that may go with code's must-answer line (MUST_ANSWER_PAUSES False): its answers to what else they
    said, never a sentence that names a must-answer topic (an answer nobody has, or its own deferral of it), leaves a
    question to a person or the viewing, thanks them for the questions (the line does), is one of code's lines (the
    commission line too: our agent answers that with the rest), promises a call or sends them to a colleague, or speaks
    of the drive to the shops with no invitation left to go with it."""
    from . import claims

    patterns = [pattern for _, pattern in (*_TOPICS, _COMMISSION)]
    kept = []
    for sentence in sentences(reply):
        if sentence in ALL_LINES or claims.is_code_line(sentence) or _LEFT_TO_A_PERSON.search(sentence) or _THANKS_FIRST.match(sentence):
            continue
        if promises_call(sentence) or sends_to_colleague(sentence):
            continue  # never a call promised, nor "please contact our colleague" (as settle cuts them elsewhere)
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in patterns):
            continue
        kept.append(sentence)
    if not any(filters.is_invitation(sentence) or filters.offers_time(sentence) for sentence in kept):
        kept = [sentence for sentence in kept if not _DRIVE.search(sentence)]
    return " ".join(kept)


def with_kept(line_text: str, kept: str) -> str:
    """Code's must-answer line with the model's other words: before the first of them that asks something (their
    one question stays last), else after them all."""
    parts = sentences(kept)
    for index, sentence in enumerate(parts):
        if rules.asks_question(sentence):
            return " ".join([*parts[:index], line_text, *parts[index:]])
    return " ".join([*parts, line_text])


# The answer: code's words where a person must act -----------------------------------------------------------

# A handover the model gave that comes before the must-answer one (its own line or its own words).
_STRONGER = ("call_requested", "customer_asked_human", "complaint_or_upset", "broker_or_for_client")


def is_call_request(answer: dict) -> bool:
    """The answer asks for a call: the model's handover call_requested, or a call it recorded as tentative."""
    handover = answer.get("handover") or {}
    proposal = answer.get("appointment") or {}
    return (handover.get("needed") and handover.get("reason") == "call_requested") or (
        proposal.get("action") == "tentative" and proposal.get("place") == "call"
    )


def call_time(answer: dict, said: str, now=None) -> dt.datetime | None:
    """The call's start the answer recorded (a tentative call with its day and time), else None."""
    proposal = answer.get("appointment") or {}
    if proposal.get("place") != "call":
        return None
    day, at = hours.parse_date(proposal.get("date")), hours.parse_time(proposal.get("time"))
    return dt.datetime.combine(day, at, tzinfo=hours.DUBAI) if day and at else None


def _plain(answer: dict, when, still_invalid: bool) -> bool:
    """Nothing in the answer that must go out instead: a booking or a time to refuse, an opt-out, a fixed line
    of another kind, a taken slot, a broker, the owner's not-a-shop line."""
    return not (
        when is not None or still_invalid or answer["opt_out"] != "none" or answer.get("slot_taken") or answer.get("broker")
        or answer.get("not_a_shop") or (answer.get("converted") not in (None, "", HOLDING))
    )


def settle(answer: dict, texts, said: str, *, shops_chat: bool, when=None, still_invalid: bool = False, quiet: bool = False,
           need=None, now=None) -> str:
    """Code's words where a person must act, set on the answer right after engine.who_they_are (live and in
    the eval, with the same values). Returns what was done ('' for nothing).

    ``texts``: their words in this burst (engine.need_texts); ``said``: the burst's words as one string;
    ``quiet``: a person has the chat already (quiet_reply answers then, never the model's words); ``need``:
    the shops customer wants no shop to rent (needs.py), whom only a request for a person or a call hands over.

    - MUST_ANSWER (shops, a shop customer): must-answer questions asked (must_answer) go to a person and get code's
      line. With MUST_ANSWER_PAUSES False the chat is not handed over: the line goes with the model's other words
      (must_answer_kept, answer["must_answer_kept"]), and engine._apply raises the QUESTIONS alert
      (answer["questions_waiting"]); a handover of the model's other than one that only says a person must answer
      (_MUST_ANSWER_COVERS) still hands it over, as MUST_ANSWER_PAUSES True does, with MUST_ANSWER_REASON. A stronger
      handover of the model's (a call, a person, a complaint, a broker) keeps its own words, with the questions listed
      in its alert (answer["must_answer"]).
    - CALL_PASSED / CALL_ASK (every playbook): a call request (the model's, or their own words asking for one,
      asks_for_call) is handed over as call_requested, and the reply says only that it went to a person, with
      the time they gave (CALL_PASSED), or asks the time that suits them (CALL_ASK); never the model's promise
      of a call. answer["call"] keeps the time for the alert and the lead's note.
    - Otherwise the model's words lose every sentence that promises a call, or sends them to contact a
      colleague themselves; in a shops handover, its questions as well (the chat goes quiet: nobody would
      answer the answer); and a handover's words that lost anything end with the holding line, unless they
      already say a colleague replies."""
    if quiet or answer["opt_out"] != "none" or answer.get("broker"):
        return ""
    plain = _plain(answer, when, still_invalid)
    handover = answer["handover"]
    asked_call = asks_for_call(said)
    if shops_chat and need is None and plain:
        topics = must_answer(texts)
        if topics:
            answer["must_answer"] = topics
            # Their words in full: a conversation line holds 500 characters, and chat 95's nine questions are more.
            answer["must_answer_words"] = " ".join(" ".join(str(text or "") for text in texts or ()).split())[:MUST_ANSWER_WORDS_MAX]
            if not (handover["needed"] and handover["reason"] in _STRONGER) and not asked_call:
                if MUST_ANSWER_PAUSES or (handover["needed"] and handover["reason"] not in _MUST_ANSWER_COVERS):
                    answer["handover"] = {"needed": True, "reason": MUST_ANSWER_REASON}
                    _code_words(answer, MUST_ANSWER)
                    return MUST_ANSWER
                # The questions to a person, and the chat goes on: code's line with the model's other words.
                kept = must_answer_kept(answer["reply"] if answer["send"] else "")
                invited = bool(answer["invited_to_meeting"]) and any(
                    filters.is_invitation(sentence) or filters.offers_time(sentence) for sentence in sentences(kept)
                )
                answer["handover"] = {"needed": False, "reason": None}
                _code_words(answer, MUST_ANSWER)
                answer["invited_to_meeting"] = invited
                answer["must_answer_kept"] = kept
                answer["questions_waiting"] = True
                return MUST_ANSWER
    # A complaint or a request for a person keeps its own words (an apology, say), the call's time going to its alert.
    stronger = handover["needed"] and handover["reason"] in ("customer_asked_human", "complaint_or_upset")
    if plain and (is_call_request(answer) or asked_call):
        # Only an hour in their own words is a time they gave: the model's call at a day and an hour it chose
        # ("call me tomorrow" recorded at 11:00) is none, and the alert then says no time was given.
        timed = call_hour(said, now)
        start = call_time(answer, said, now) if timed else None
        answer["call"] = {"start": start.isoformat() if start else None, "words": " ".join(str(said or "").split())[:255]}
        if not stronger:
            answer["handover"] = {"needed": True, "reason": "call_requested"}
            kind = CALL_PASSED if timed else CALL_ASK
            _code_words(answer, kind)
            return kind
    if not answer["reply"] or answer.get("converted"):
        return ""
    handed = answer["handover"]["needed"]
    kept, cut = [], []
    for sentence in sentences(answer["reply"]):
        if sentence in ALL_LINES:
            kept.append(sentence)
        elif promises_call(sentence):
            cut.append("call_promise")
        elif sends_to_colleague(sentence):
            cut.append("colleague")
        elif shops_chat and handed and rules.asks_question(sentence):
            cut.append("handover_question")
        else:
            kept.append(sentence)
    if not cut:
        return ""
    if handed and not any(sentence in ALL_LINES or _COLLEAGUE_REPLIES.search(sentence) for sentence in kept):
        kept.append(line(HOLDING, answer["language"], shops=shops_chat))
    answer["reply"] = " ".join(kept).strip()
    answer["trimmed"] = [*(answer.get("trimmed") or []), *dict.fromkeys(cut)]
    if not answer["reply"]:
        answer["send"] = False
    return "trimmed"


def _code_words(answer: dict, kind: str) -> None:
    """The answer's words become code's line ``kind``: no invitation, no location, no shop step."""
    answer["converted"] = kind
    answer["invited_to_meeting"] = False
    answer["share_office_location"] = False
    answer["send"] = True
    answer.pop("shop_step", None)


def converted_line(kind: str, language: str, *, shops: bool) -> str:
    """The words of a converted answer: this module's lines (a shops holding line among them), else rules'."""
    if kind in KINDS:
        return line(kind, language, shops=shops)
    return rules.line(kind, language)


# While a person has the chat ------------------------------------------------------------------------------


def quiet_reply(texts, language: str, *, shops: bool, reason: str = "", answer: dict | None = None, said: str = "",
                now=None, line_due: bool = True, holding_due: bool = True) -> tuple[str, str]:
    """(what it is, the words) for a burst while a person has the chat (handed over), live and in the eval:

    - QUIET_CLOSING, '': every message is a thanks or a goodbye (is_closing; chat 57);
    - QUIET_CHASE: they are still waiting (is_chase; chat 88's "will i get any call??"): the apology, and the
      team is alerted again (engine._apply), the line at most every QUIET_LINE_EVERY (``line_due``);
    - QUIET_CALL: they ask for a call in their own words (asks_for_call, or the model's call request with a
      call spoken of), or give an hour for the one they asked for (the handover's reason call_requested):
      CALL_PASSED with a time, else CALL_ASK, passed on to the team (engine._apply), the line as a chase's;
    - QUIET_HOLDING: anything else, the holding line every two hours (``holding_due``), as before.
    ``texts``: what they said, acknowledgements aside; ``reason``: the handover's; ``answer``: the model's,
    whose words never go out here (the model is told to set send false while a person has the chat)."""
    said_texts = [str(text or "") for text in texts or () if str(text or "").strip()]
    if said_texts and all(is_closing(text) or rules.is_acknowledgement(text) for text in said_texts):
        return QUIET_CLOSING, ""
    if any(is_chase(text) for text in said_texts):
        return QUIET_CHASE, (line(CHASE, language, shops=shops) if line_due else "")
    answer = answer or {}
    words = " ".join(str(said or "").split()) or " ".join(said_texts)
    asked = asks_for_call(words) or (bool(answer) and is_call_request(answer) and bool(_CALL_WORD.search(words)))
    timed = call_hour(words, now)
    # An hour for a visit ("I can come at 5") is no call time: the holding line, and the person reads it.
    if asked or (reason == "call_requested" and timed and not (_VISIT.search(words) and not _CALL_WORD.search(words))):
        return QUIET_CALL, (line(CALL_PASSED if timed else CALL_ASK, language, shops=shops) if line_due else "")
    return QUIET_HOLDING, (line(HOLDING, language, shops=shops) if holding_due else "")


# Who hears it -------------------------------------------------------------------------------------------


def chat_link() -> str:
    """Where a person answers a Lead AI chat: the WhatsApp panel inside Bitrix, on its Lead AI screen."""
    from . import alerts

    portal = str(getattr(settings, "BITRIX_PORTAL_URL", "") or "").rstrip("/")
    return f"{portal}{alerts.PANEL_PATH}" if portal else alerts.PANEL_PATH


def where_lines(conversation, chat) -> list[str]:
    """The alert's lines that say where the customer is: their lead (the shops campaign's own, or the chat's CRM
    record) and the chat on the Lead AI screen."""
    from . import crm_fields

    lines = []
    try:
        lead = crm_fields.lead_of(chat, conversation)
    except Exception:  # noqa: BLE001 - an alert never fails on its extra lines
        lead = None
    if lead:
        lines.append(f"Lead: {lead}")
    elif chat is not None and chat.crm_entity and chat.crm_id:
        lines.append(f"CRM record: {chat.crm_entity.replace('_', ' ')} {chat.crm_id}")
    lines.append(f"Chat: {chat_link()} (WhatsApp, Lead AI screen, +{conversation.contact.wa_id})")
    return lines


def words_line(words: str, label: str = "Their last words", limit: int = WORDS_MAX) -> str:
    """'Their last words: ...' on one line with no BB-code or HTML (crm's own table; crm.safe would stop at 255
    characters, and chat 95's nine questions are more), or '' with none."""
    from . import crm

    text = " ".join(str(words or "").split()).translate(crm._UNSAFE)[:limit]
    return f"{label}: {text}" if text else ""


def call_lines(call: dict | None, appointment=None) -> list[str]:
    """What a call alert or note says of the time asked: the call's start, else their words, else none yet."""
    start = None
    if appointment is not None and getattr(appointment, "place", "") == "call" and appointment.starts_at:
        start = appointment.starts_at
    elif call and call.get("start"):
        try:
            start = dt.datetime.fromisoformat(str(call["start"]))
        except ValueError:
            start = None
    words = (call or {}).get("words") or (getattr(appointment, "customer_words", "") if appointment is not None else "")
    if start is not None:
        lines = [f"Call asked for: {hours.describe(start)}"]
    elif words and call_hour(words):
        lines = ["Call asked for: the time in their words below"]
    else:
        lines = ["Call asked for: no time given yet"]
    if words:
        lines.append(words_line(words, "Their words"))
    return lines


def call_note_lines(call: dict | None, appointment=None, *, again: bool = False) -> list[str]:
    """The lead's timeline note for a call request (tasks.record_crm_note "call", crm.note_text)."""
    lines = [line_ for line_ in call_lines(call, appointment) if line_]
    lines.append(
        "They gave the time for the call they asked for: please call them then and note the outcome here."
        if again
        else "Nobody has called yet: please call them and note the outcome here. The assistant promised no time."
    )
    return lines


# One more alert for a handover nobody answered -----------------------------------------------------------------


def office_minutes(start: dt.datetime, end: dt.datetime, closed_dates=()) -> float:
    """Minutes of office time (an open day, hours.OPEN to hours.CLOSE, Dubai) between ``start`` and ``end``."""
    if end <= start:
        return 0.0
    total = 0.0
    day = start.astimezone(hours.DUBAI).date()
    last = end.astimezone(hours.DUBAI).date()
    while day <= last:
        if hours.is_open_day(day, closed_dates):
            opens = dt.datetime.combine(day, hours.OPEN, tzinfo=hours.DUBAI)
            closes = dt.datetime.combine(day, hours.CLOSE, tzinfo=hours.DUBAI)
            begin, finish = max(start, opens), min(end, closes)
            if finish > begin:
                total += (finish - begin).total_seconds() / 60
        day += dt.timedelta(days=1)
    return total


def office_open(now, closed_dates=()) -> bool:
    local = hours.now_dubai(now)
    return hours.is_open_day(local.date(), closed_dates) and hours.OPEN <= local.time() < hours.CLOSE


# The most candidates one sweep reads (a page at a time), so the ones nobody can escalate never hide a due one (review 2d).
ESCALATE_READ_AT_MOST = 1000


def escalate_waiting(now) -> int:
    """One more alert, once per handover, for a shops chat handed to a person in which nobody from the team has
    written for ESCALATE_AFTER of office time (launch review issue 3: seven chats had no person's reply two to
    four and a half hours after their alerts); and once per QUESTIONS alert, for must-answer questions nobody
    answered while the chat went on (MUST_ANSWER_PAUSES False). Only during office hours, to the chat's people and
    the Lead AI alert list (kind WAITING, in alerts.LISTED_KINDS), high priority. Not for a handover a person made
    or took in Bitrix (HANDED_REASON, a Broker set there, a pause after the handover), a chat an agent paused,
    stopped, not interested, on the opt-out registry, transferred or no longer on the Lead AI screen. The shops
    chats are picked, and the handovers escalated already left out, in the query, and the candidates read a page at
    a time (review 2d: a hundred older handovers of any playbook filled the one page read, for days). How many went."""
    from ..models import LeadAiAlert, LeadAiChatState, LeadAiSettings

    settings_row = LeadAiSettings.load()
    closed = settings_row.closed_dates
    if not office_open(now, closed):
        return 0
    sent = 0
    handovers = (
        LeadAiChatState.objects.filter(
            handed_over_at__isnull=False,
            handed_over_at__lte=now - ESCALATE_AFTER,
            handed_over_at__gte=now - ESCALATE_WITHIN,
            stopped_at__isnull=True,
            not_interested_at__isnull=True,
        )
        .filter(Q(paused_at__isnull=True) | Q(paused_by__isnull=True))
        .exclude(handover_reason=_bitrix_handed())
    )
    shops = _shops_conversations(handovers.values_list("conversation_id", flat=True))
    escalated = LeadAiAlert.objects.filter(kind=WAITING, conversation_id=OuterRef("conversation_id"), created_at__gte=OuterRef("handed_over_at"))
    rows = (
        handovers.filter(conversation_id__in=shops)
        .exclude(Exists(escalated))
        .select_related("conversation__contact", "conversation__assigned_agent")
        .order_by("handed_over_at", "pk")
    )
    read, after = 0, None
    while read < ESCALATE_READ_AT_MOST:
        # A page at a time, from where the last one ended (one escalated meanwhile leaves the query, so no offset).
        page_rows = rows if after is None else rows.filter(Q(handed_over_at__gt=after[0]) | Q(handed_over_at=after[0], pk__gt=after[1]))
        page = list(page_rows[:ESCALATE_PAGE])
        for state in page:
            if _escalate(state.conversation, state, now, settings_row, since=state.handed_over_at, handover=True):
                sent += 1
        if len(page) < ESCALATE_PAGE:
            break
        read += len(page)
        after = (page[-1].handed_over_at, page[-1].pk)
    sent += _escalate_questions(now, settings_row)
    if sent:
        logger.info("Lead AI escalated %s handover(s) or question(s) nobody answered", sent)
    return sent


def _bitrix_handed() -> str:
    from .. import bitrix_status

    return bitrix_status.HANDED_REASON


def _shops_conversations(ids) -> list:
    from .. import lane

    return sorted(pk for pk, playbook in lane.playbooks(set(ids)).items() if playbook in ESCALATE_PLAYBOOKS)


def _escalate_questions(now, settings_row) -> int:
    """The WAITING alert for must-answer questions nobody answered while the chat went on (a QUESTIONS alert of
    ESCALATE_AFTER of office time ago and more, within ESCALATE_WITHIN): once per QUESTIONS alert."""
    from ..models import LeadAiAlert, LeadAiChatState

    rows = (
        LeadAiAlert.objects.filter(kind=QUESTIONS, created_at__lte=now - ESCALATE_AFTER, created_at__gte=now - ESCALATE_WITHIN)
        .order_by("created_at", "pk")
        .values_list("conversation_id", "dedupe_key", "created_at")[:ESCALATE_READ_AT_MOST]
    )
    first: dict = {}
    for conversation_id, key, created in rows:
        first.setdefault((conversation_id, (key or "").rsplit(":", 1)[0]), created)
    shops = set(_shops_conversations({conversation_id for conversation_id, _ in first}))
    sent = 0
    for (conversation_id, _base), created in first.items():
        if conversation_id not in shops:
            continue
        state = LeadAiChatState.objects.filter(conversation_id=conversation_id).select_related("conversation__contact", "conversation__assigned_agent").first()
        if state is None or state.handed_over_at is not None:
            continue  # handed over since: the handover's own escalation has it
        if _escalate(state.conversation, state, now, settings_row, since=created, handover=False):
            sent += 1
    return sent


def _escalate(conversation, state, now, settings_row, *, since, handover: bool) -> bool:
    """The WAITING alert for one handover (``handover``) or one set of must-answer questions, since ``since``, when it is
    due: True when one went."""
    from apps.inbox.models import Message

    from .. import optout
    from ..models import LeadAiAlert, LeadAiChat
    from . import alerts, engine, escalation, transcript

    if conversation.linked_conversation_id or state.stopped_at is not None or state.not_interested_at is not None:
        return False
    if state.paused_at is not None and (state.paused_by_id is not None or not handover or state.paused_at > since):
        return False  # an agent paused it, or someone took it in Bitrix after the handover
    chat = LeadAiChat.objects.filter(conversation=conversation, active=True).first()
    if chat is None or not settings_row.answers(conversation.contact.wa_id) or optout.is_blocked(conversation.contact.wa_id):
        return False
    waited = office_minutes(since, now, settings_row.closed_dates)
    if waited < ESCALATE_AFTER.total_seconds() / 60:
        return False
    base = f"{WAITING}:{conversation.pk}:{'' if handover else 'q'}{since:%Y%m%d%H%M%S}"
    if LeadAiAlert.objects.filter(conversation=conversation, kind=WAITING, dedupe_key__startswith=f"{base}:").exists():
        return False
    if LeadAiAlert.objects.filter(conversation=conversation, kind="bitrix_status", created_at__gte=since).exists():
        return False  # a person set a Bot Status in Bitrix since (Handed to agent, Broker): they have it
    if engine.person_wrote_since(conversation, since):
        return False
    newest = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND)
        .exclude(kind__in=engine.SKIP_KINDS)
        .order_by("-pk")
        .first()
    )
    words = transcript.inbound_text(newest, transcript.transcript_text(newest)) if newest is not None else ""
    who = engine._customer_name(conversation, state.facts or {}) or f"+{conversation.contact.wa_id}"
    if handover:
        head = (
            f"{who} (WhatsApp +{conversation.contact.wa_id}) {engine.HANDOVER_TEXT.get(state.handover_reason, 'needs a person')}. "
            f"The assistant handed the chat to a person at {transcript.stamp(since)}, and nobody from the team has written in it "
            f"since ({int(waited)} minutes of office time)."
        )
    else:
        head = (
            f"{who} (WhatsApp +{conversation.contact.wa_id}) asked questions a person must answer before any visit, at "
            f"{transcript.stamp(since)}, and nobody from the team has written in the chat since ({int(waited)} minutes of office "
            "time). The assistant told them our agent would answer them there."
        )
    lines = [head, words_line(words), *where_lines(conversation, chat), "Please reply to them in the chat now, or ask a colleague to."]
    # A handover nobody answered reaches the responsible's team lead and department head too (escalation.above, Cursor's
    # C49 map; the advance plan's D): the lead's responsible, else the chat's owner (a lead held by Bitrix user 0 or 1 is
    # nobody's: the owner's people are asked, as alerts.recipients reads it).
    above = []
    if handover:
        owner = conversation.assigned_agent
        above = escalation.above(alerts._bitrix_target(state.responsible_bitrix_user_id) or getattr(owner, "bitrix_user_id", ""))
        if above:
            lines.append("The responsible's team lead and department head were sent this alert too.")
    return bool(
        alerts.raise_alert(
            kind=WAITING,
            conversation=conversation,
            priority="high",
            title=f"Still waiting for a person: {who}"[:200],
            text="\n".join(item for item in lines if item),
            dedupe_key=base,
            crm_url=engine._crm_url(chat),
            also=above,
        )
    )
