"""A broker is never served as an end user (Q11; the launch gate, 2026-10-17).

Q11 (owner's choice 2026-10-13): a broker, or someone asking for a client, gets the shops build pack's hand-off line,
the inbox label Broker and a pause until an agent presses Resume AI (engine.settle, engine._apply), and on the lead
Purpose Broker and Bot Status Broker (crm_fields.turn_writes). The model tags it (handover broker_or_for_client), as
SHOPS_SYSTEM's FOR WHOM says. The real-model eval shops-broker caught it, in both runs, recording facts.for_client true
for "I am an agent, I am checking for my client. He needs a shop around 500 sq ft" with no handover at all, and
serving the agent: "For your client, a Type 1 shop is perfect ...".

``backstop`` hands such a shops turn over as the model's own tag would, right after the model (live and in the eval,
after engine.untag_need), so every step after it reads the answer a tag would have given:

- the model recorded facts.for_client true this turn (it was not true before) and handed the chat to nobody, and
  their words this burst say nothing that makes them an end user (``end_user``); or
- their own words this burst say they are an agent or a broker, or source the shop for a client (``declares``). These
  hand over even when the model set nothing, and over a handover of the model's that code may lift later (OVER_WEAKER:
  people.settle lifts a must-answer "legal" one, so "I am a broker. What is the deposit?" would go on being served),
  never over a call, a person or a complaint asked for (KEEPS).

Their words, strongest first (``declares``):
- I am / we are an agent or a broker (EXPLICIT): "I am an agent", "I'm a real estate broker", "we are a brokerage",
  "we r agents", "Am broker" (their "I" left out, opening the message), "I am Ahmed, a real estate agent." (an article
  or a real-estate kind, and the clause ends there or names their firm); Roman Urdu "main broker hoon", "hum agent hain",
  "main dealer hoon";
  Arabic "أنا وسيط", "أنا سمسار", "نحن مكتب عقاري"; Urdu script and Devanagari "میں بروکر ہوں", "मैं ब्रोकर हूँ";
- other words of theirs as one (ROLE): "Broker here" opening the message (never in a question), "As a broker, do you
  share commission?", "This is Neeta here from AR Properties", "Ali from Betterhomes here", "I'm from Betterhomes";
- a client of theirs (the client words): "for my client", "my client needs ...", "I have a client looking for a shop",
  "my customer needs ...", "I have a tenant for your shop", "I will bring my client at 5pm", "for a client" as theirs
  ("Any shop for client?", "Do you have Type 2 for a client"), "client" or "for a client" as their whole answer;
  Roman Urdu "client ke liye", "mere client ko shop chahiye", "customer ke liye"; Arabic "لعميل", "عندي عميل", "عميلي";
- "Agent" or "Broker" alone, only as their answer to our for-whom question (``asked_for_whom``).

Only EXPLICIT counts in a chat a person already holds (``held``: "I'm outside, agent not picking up" is our agent), or
when anything says they are the end user (``told_end_user``: the answer or the chat's facts hold for_client false, the
chat knows their business; ``self_words``: the burst says "for myself", "for me", "apne liye", "لي شخصياً"): there
"I have a client at 3" is a salon owner's, never a broker's. The model's for_client alone never hands over a held chat.

Never theirs as a broker:
- a trade named before the word ("travel agent", "insurance broker", "customs broker"), "an agent for Etisalat",
  someone else's words or deeds ("a broker told me"), a no before it ("not as an agent", "I am not a broker"), a fee or
  a past before "as a broker" ("as broker commission", "I used to work as a broker"), our agent ("agent not here",
  "Office mein agent hai?": "mein", "me" and "mai ... hai" say "in");
- a client sought ("looking for a client"), awaited ("waiting for a client"), or busy with them ("I have a client at
  3", "I have a client appointment", "my client is here", "عندي زبون الحين"); a client's facilities ("Need parking for
  client", "client ke liye parking chahiye", "mere client ko parking chahiye"); a discount or a price for one;
- words about us (``about_us``): "you" or "your" before the word in a phrase about us ("Who is your client?", "Are you
  an agent?", "Are you checking for a client?"), "Which client?", "What do you mean, for a client?", our word said back
  alone ("client?"). Never a question mark alone, nor a "you" after the word ("I will share with my client and let you
  know"): brokers ask ("Any shop for client?", "Do you work with brokers?").

Never, against the model's for_client alone (``end_user``):
- a business owner speaking of their own customers (``own_customers``: "I need a shop to serve my clients", "my clients
  come to my salon", "client meetings", "for my clients, I have a salon", "I have a travel agency ... for my clients"),
  read clause by clause, and never in a burst that names someone else's client ("My client needs a shop with parking
  for customers": a broker describing his client's business);
- family, a friend or a partner ("Yes, I need one more for my brother", "My friend needs one", "my partner and I"):
  eval shops-rented-licence-no keeps "Yes, I need one more for my brother's salon" an end user (facts.for_client
  false), SHOPS_SYSTEM's OLD-LEAD MODE thanks someone who knows someone and says that person can message us here, and
  shops-rented-friend-63 is a referral, never lost; the rule is theirs, read here as it is;
- "for myself" said in the burst (SELF);
- "client" (or "agent", "broker") only in words about us (ABOUT_US).
Their own words as an agent beat all of these, as SHOPS_SYSTEM says ("For a client, as a broker or an agent"); a
business owner's words take back only the client words of many ("for my clients" then), never "I am a broker".

Not in a chat that carries the Broker label already (``labelled``: an agent pressed Resume AI, or labelled it; the
chat is theirs, as engine.settle's broker_labelled says), nor over an opt-out.

Plain functions on plain data (``labelled`` aside, which the engine passes as a query asked only when the backstop
would act), so the eval decides exactly as the engine does.
"""

from __future__ import annotations

import re

from . import rules

# The handover the model's tag and this backstop give (engine.BROKER).
REASON = "broker_or_for_client"
# Handovers their own words never replace: a call, a person or a complaint asked for (people._STRONGER, the broker aside).
KEEPS = ("call_requested", "customer_asked_human", "complaint_or_upset")
# What handed the turn over (answer["broker_backstop"], the turn's actions).
WORDS = "words"
FACTS = "facts"
# Why the model's for_client alone is no broker (end_user).
OWN_CUSTOMERS = "own_customers"
FAMILY = "family"
SELF = "self"
ABOUT_US = "about_us"
# Why only EXPLICIT words count (told_end_user).
SAID_FOR_ME = "for_client_false"
KNOWN_BUSINESS = "business_known"

# The owner's defaults (2026-10-17), one constant each:
# - the backstop itself; False leaves every broker to the model's tag, as before;
BACKSTOP = True
# - their own words as an agent replace a handover of the model's that code may lift (any but KEEPS).
OVER_WEAKER = True

_AR = r"\u0621-\u064a\u0671-\u06d3"
_NOT_AR_BEFORE = f"(?<![{_AR}])"
_NOT_AR_AFTER = f"(?![{_AR}])"

# Only a real-estate kind may stand before the word ("real estate agent", "RERA registered broker"); any other is a
# trade of theirs ("travel agent", "insurance broker"). "An agent for Etisalat" or "of Huawei" is a dealer's; "an agent
# for my client" is ours.
_KIND = (
    r"(?:real\s*estate|realestate|property|properties|leasing|rental|letting|commercial|rera|registered|licen[cs]ed|freelance"
    r"|freelancer|independent)"
)
_ESTATE = r"(?:real\s*estate|realestate|property|properties|leasing|rental|letting)"
_ROLE_NOUN = r"(?:agents?|brokers?|realtors?|brokerage|brokerages)"
_ESTATE_NOUN = r"(?:agency|agencies|dealers?|consultants?|consultancy|advisors?|advisers?|company|companies|firm|office)"
_THEIR_PEOPLE = r"(?:(?:my|our|a|an|the|one|some|your)\s+)?(?:clients?|customers?|buyers?|tenants?|investors?|landlords?|owners?|people)\b"
_OF_FOR = r"(?!\s+(?:of|for)\s+(?!" + _THEIR_PEOPLE + r"))"
# An agent or a broker who did something: someone else ("a broker told me", "as an agent said").
_SOMEONE_ELSES = (
    r"(?!\s+(?:told|tells|said|says|asked|asks|called|calls|sent|sends|showed|shows|gave|gives|is|was|has|had|will|would|can"
    r"|could)\b)"
)
_GREETING = r"(?:(?:hi|hello|hey|salam|salaam|assalam\w*|aoa|dear\s+\w+|sir|madam)[\s,!.]+)*"

# I am / we are an agent or a broker: the only words that count in a chat a person holds, or of an end user.
# (Never a bare "working as": "I was working as an agent" is a past, read by _role.)
_SUBJECT = (
    r"(?:i\s*am|i'?m|im|i\s+m|we\s*are|we'?re|we\s+r|v\s+r|i\s+work\s+as|we\s+work\s+as|i\s+am\s+working\s+as|i'?m\s+working\s+as"
    r"|we\s+are\s+working\s+as)"
)
_FILLER = r"(?:(?:also|just|only|actually|basically|myself|ourselves|an?|one)\s+)*"
# A real-estate firm by its name: "AR Properties", "Prime Properties", "Betterhomes", "Allsopp & Allsopp" (never "the
# property next door", "Dubai looking for property": a name's words are no verb, article or preposition).
_NAME_WORD = (
    r"(?!(?:looking|searching|seeking|need|needs|want|wants|for|in|at|to|and|or|a|an|the|any|some|your|my|our|this|that|i|we)\b)"
    r"[\w&'.-]+\s+"
)
_FIRM = (
    r"(?:" + _NAME_WORD + r"){0,3}?"
    r"(?:\w*propert(?:y|ies)|real\s*estate|realestate|\w*realty|realtors?|\w*homes|brokerage|brokers|allsopp"
    r"|haus\s*(?:&|and)\s*haus|espace|provident|hamptons|savills|knight\s+frank|cbre|jll|asteco|sotheby'?s?|coldwell)\b"
)
_EXPLICIT = re.compile(
    # "I am an agent", "I'm a real estate broker", "we are a brokerage", "we r agents", "I am a property consultant".
    r"\b" + _SUBJECT + r"\s+" + _FILLER
    + r"(?:(?:" + _KIND + r"\s+){0,2}" + _ROLE_NOUN + r"|" + _ESTATE + r"\s+" + _ESTATE_NOUN + r")\b" + _OF_FOR
    # "I'm from a real estate agency", "we are with a brokerage".
    + r"|\b" + _SUBJECT + r"\s+(?:also\s+|just\s+)?(?:from|with)\s+(?:an?\s+)?(?:" + _KIND + r"\s+)?(?:brokerages?|" + _ESTATE
    + r"\s+" + _ESTATE_NOUN + r")\b"
    # "Am broker", "am an agent": their "I" left out, opening what they say (chat 57's "am looking for studio").
    + r"|^\W*" + _GREETING + r"am\s+" + _FILLER + r"(?:" + _KIND + r"\s+){0,2}(?:agents?|brokers?|realtors?)\b(?!\s*\?)" + _OF_FOR
    # "I am Ahmed, a real estate agent.", "I'm Ali, an agent at Betterhomes": an article or a real-estate kind, and the
    # clause ends there or names their firm (never "I'm here, agent not here", "I am Ali, agent for du").
    + r"|\b(?:i\s*am|i'?m|im|this\s+is|my\s+name\s+is|myself)\s+\w+(?:\s+\w+)?\s*,\s*(?:an?\s+(?:" + _KIND + r"\s+){0,2}|(?:"
    + _KIND + r"\s+){1,2})(?:agent|broker|realtor)(?:(?=\s*(?:[.,;:!]|$))|\s+(?:at|from|with)\s+" + _FIRM + r")"
    # Roman Urdu: "main agent hoon", "mai broker hu", "hum broker hain", "main dealer hoon" (never "Office mein agent
    # hai?", "office me agent hai kya", "office mai agent hai": "mein", "me" and "mai ... hai" say "in").
    + r"|\b(?:main|mai)\s+(?:bhi\s+|ek\s+|aik\s+)?(?:real\s*estate\s+|property\s+)?(?:agent|broker|dalal|realtor|dealer)"
    + r"\s+(?:hoon|hun|hu|hon|hn|hoo)\b"
    + r"|\b(?:hum|ham)\s+(?:bhi\s+)?(?:real\s*estate\s+|property\s+)?(?:agents?|brokers?|dalal|realtors?|dealers?)"
    + r"\s+(?:hain|hai|hein|hen|hn)\b"
    # Arabic: "أنا وسيط (عقاري)", "انا سمسار", "أنا بروكر", "أنا وكيل عقاري", "أنا مسوق عقاري", "نحن مكتب عقاري".
    + r"|" + _NOT_AR_BEFORE + r"[وف]?(?:أنا|انا|إنا|نحن|احنا|إحنا)\s+(?:(?:وسيط|سمسار|بروكر)ة?|وسطاء|سماسرة"
    + r"|(?:وكيل|وكلاء|مسوق|مسوقة)\s+(?:عقاري|عقارية|عقارات)|(?:مكتب|شركة)\s+(?:عقاري|عقارات|وساطة))" + _NOT_AR_AFTER
    # Urdu script and Devanagari: "میں بروکر ہوں", "ہم ایجنٹ ہیں", "मैं एजेंट हूँ" (never "آفس میں ایجنٹ ہے؟": "میں" is "in" too).
    + r"|میں\s+(?:بھی\s+|ایک\s+)?(?:پراپرٹی\s+)?(?:بروکر|ایجنٹ|دلال|ڈیلر)\s+ہوں"
    + r"|ہم\s+(?:بھی\s+)?(?:پراپرٹی\s+)?(?:بروکر|ایجنٹ|دلال|ڈیلر)\s+(?:ہیں|ہے)"
    + r"|(?:मैं|मै)\s+(?:भी\s+|एक\s+)?(?:प्रॉपर्टी\s+)?(?:ब्रोकर|एजेंट|दलाल|डीलर)\s+(?:हूँ|हूं|हु)"
    + r"|हम\s+(?:भी\s+)?(?:प्रॉपर्टी\s+)?(?:ब्रोकर|एजेंट|दलाल|डीलर)\s+(?:हैं|है)",
    re.IGNORECASE,
)
# Other words of theirs as an agent: counted where nothing says they are the end user and nobody holds the chat.
_ROLE = re.compile(
    # "Broker here", "Hi, agent here" opening what they say (never "The broker here told me ...", "I reached the office.
    # Agent here?").
    r"^\W*" + _GREETING + r"(?:an?\s+)?(?:real\s*estate\s+|property\s+)?(?:agent|broker|realtor)\s+here\b(?!\s*\?)"
    # "As a broker, do you share commission?", "I'm asking as an agent" (never "As an agent told me ...", "as broker
    # commission", "as agent fee").
    + r"|(?<!such\s)(?<!same\s)\bas\s+(?:an?\s+)?(?:" + _KIND + r"\s+)?(?:agent|broker|realtor)\b" + _SOMEONE_ELSES
    + r"(?!\s+(?:fee|fees|commission|commissions|charge|charges|cut|percentage|percent)\b)"
    + r"(?!\s+(?:of|for)\s+(?!" + _THEIR_PEOPLE + r"))"
    # "Hi This is Neeta here from AR Properties", "This is Ali from Prime Properties", "Hi, Ali from Betterhomes here",
    # "I'm from Betterhomes".
    + r"|\bthis\s+is\s+(?:\w+\s+){1,3}?(?:here\s+)?(?:from|with|at)\s+" + _FIRM
    + r"|\b\w+\s+(?:from|with)\s+" + _FIRM + r"\s+here\b"
    + r"|\b(?:i\s*am|i'?m|im|we\s*are|we'?re|we\s+r)\s+(?:calling\s+|writing\s+|messaging\s+)?(?:from|with)\s+" + _FIRM,
    re.IGNORECASE,
)
# A fee, a payment or a past before "as a broker": "What's the commission as broker?", "I used to work as a broker".
_NOT_A_ROLE_BEFORE = re.compile(
    r"\b(?:pay|paying|paid|commission|commissions|fee|fees|charge|charges|percent|percentage|used\s+to|was|were|former|formerly"
    r"|before|previously|ex|earlier|retired|had\s+been|worked)\b",
    re.IGNORECASE,
)
_AS_ROLE = re.compile(r"\bas\s+(?:an?\s+)?(?:\w+\s+)?(?:agent|broker|realtor)\b", re.IGNORECASE)

# The client words. A client at a time, coming or with them now is an owner's own, busy ("I have a client at 3, can I
# come at 5?", "I have a client call at 4", "my client is here, I'll reply later"); so is one sought or awaited, and a
# client's parking, a discount or a price.
_MINE = r"(?:my|our)"
_CLIENT_NOUNS = (
    r"(?:meeting|meetings|area|lounge|parking|waiting|seating|reception|visit|visits|base|service|services|traffic|appointment"
    r"|appointments|call|calls|session|sessions|booking|bookings)"
)
_TO_COME = r"(?!\s+to\s+(?:come|visit|sit|wait|park|meet|relax|enjoy|shop|feel|stay)\b)"
_NOT_A_NOUN = r"(?!\s+" + _CLIENT_NOUNS + r"\b)"
_AT_A_TIME = r"(?!\s+(?:at|around|till|until|coming|now|right\s+now|in\s+(?:\d+|an?|half))\b)(?!\s*[@\d])"
_HERE_NOW = r"(?!(?:\s+is|'s)\s+(?:here|waiting|with\s+me|sitting\s+with\s+me)\b)"
_AR_NOW = r"(?!\s+(?:الحين|الآن|الان|حاليا|حالياً|دحين|هلق|توه|هسه|هسا))"
_VERBS = (
    r"(?:is|was|has|had|needs?|wants?|requires?|asked|asks|asking|would|will|can|could|may|might|likes?|liked|prefers?|plans?"
    r"|planning|wishes|looking|searching|interested|already|also|just|really|urgently|see|view|visit|come|check|inspect|saw"
    r"|seen|told|said|sent)"
)
_SPACES = r"(?:shops?|stores?|units?|space|spaces|property|properties|places?|outlets?)"
# One client of theirs, in the first person: true even in a question ("Can my client see it tomorrow?"). It names
# someone else's client, so a business owner's words never take it back (own_customers).
_MINE_ONE = re.compile(
    # "for my client", "on behalf of one of our clients" (never "for my client meetings", "for my client to come").
    r"\b(?:for|on\s+behalf\s+of)\s+(?:" + _MINE + r"\s+client\b(?!'s\b)|(?:one|some|two|a\s+few)\s+of\s+" + _MINE + r"\s+clients\b)"
    + _NOT_A_NOUN + _TO_COME
    # "my client is looking", "my client needs", "can my client see it", "my client's restaurant" (never "my client is
    # here", "my client is waiting").
    + r"|\b" + _MINE + r"\s+client\b" + _HERE_NOW + r"(?:'s\b|\s+" + _VERBS + r"\b)"
    # "my clients are looking for shops".
    + r"|\b" + _MINE + r"\s+clients\s+(?:are\s+|is\s+)?(?:looking|searching|need|needs|want|wants|require|requires|interested)"
    + r"\s+(?:in\s+|for\s+)?(?:a\s+|an\s+|some\s+|the\s+)?" + _SPACES + r"\b"
    # "I have a client", "I've got a client who ..." (never "I have a client at 3", "I have a client appointment").
    + r"|\b(?:i|we)\s*(?:have|'ve|ve|got|have\s+got|'ve\s+got)\s+(?:got\s+)?(?:a|one|1|another|an\s+other)\s+client\b"
    + _NOT_A_NOUN + _AT_A_TIME
    # "we have clients looking for shops", "I have two clients who need a unit" (never "many clients who live in IC").
    + r"|\b(?:i|we)\s*(?:have|'ve|ve|got|have\s+got|'ve\s+got)\s+(?:got\s+)?(?:(?:some|two|2|three|3|few|a\s+few|many|several"
    + r"|multiple)\s+)?clients\s+(?:(?:who|that)\s+(?:are\s+)?)?(?:looking|searching|interested|needing|wanting|requiring|asking"
    + r"|need|needs|want|wants|require)\b"
    + r"|\b(?:i|we)\s*(?:have|'ve|ve|got)\s+(?:got\s+)?(?:(?:some|two|2|three|3|few|a\s+few|many|several|multiple)\s+)?clients"
    + r"\s+for\s+(?:a\s+|the\s+|your\s+)?" + _SPACES + r"\b"
    + r"|\bclients?\s+of\s+(?:mine|ours)\b"
    # By another name: "My customer needs 500 sqft shop", "For my customer", "I have a tenant for your shop", "I have a
    # party looking for a shop", "my buyer wants ...".
    + r"|\b" + _MINE + r"\s+(?:customer|tenant|buyer|party|investor)\s+(?:is\s+)?(?:looking|searching|interested|needs?|wants?"
    + r"|requires?)\b"
    + r"|\bfor\s+" + _MINE + r"\s+customer\b(?!'s\b)" + _NOT_A_NOUN + _TO_COME
    + r"|\b(?:i|we)\s*(?:have|'ve|ve|got)\s+(?:got\s+)?(?:a|one|1|another)\s+(?:customer|tenant|buyer|party|investor)\s+"
    + r"(?:for|looking|searching|interested|who|that|needs?|wants?)\b"
    # What they do with their client: "I will bring my client at 5pm", "I'll come with my client tomorrow at 11", "Can I
    # see the shop with my client?", "I will share with my client and let you know".
    + r"|\b(?:bring|bringing|brought|show|showing|ask|asking|inform|informing|tell|telling|update|updating|come\s+with"
    + r"|coming\s+with|came\s+with|visit\s+with|share\s+(?:\w+\s+){0,2}?with|discuss\s+(?:\w+\s+){0,2}?with|check\s+with"
    + r"|confirm\s+with|see\s+(?:\w+\s+){0,2}?with|view\s+(?:\w+\s+){0,2}?with)\s+" + _MINE + r"\s+client\b(?!'?s\b)"
    # Roman Urdu: "mere paas ek client hai" (never "mere paas client hai abhi").
    + r"|\b(?:mere|mery|meray|hamare|humare)\s+(?:pass|paas|pas)\s+(?:ek\s+|aik\s+|1\s+)?client\b(?!(?:\s+\w+){0,2}\s+(?:abhi|filhal)\b)"
    # Arabic: "عميلي", "لعميلي", "لأحد عملائي", "عندي عميل" (never "عندي زبون الحين", "معي عميل الحين"), "نيابة عن عميلي".
    + r"|" + _NOT_AR_BEFORE + r"[وف]?ل?(?:عميلي|عميلتي|لأحد\s+عملائي|لاحد\s+عملائي)" + _NOT_AR_AFTER
    + r"|" + _NOT_AR_BEFORE + r"[وف]?(?:عندي|لدي|لديّ|معي|عندنا|لدينا|معنا)\s+(?:عميل|عميلة|زبون)" + _NOT_AR_AFTER + _AR_NOW
    + r"|نيابة\s+عن\s+(?:عميل|عميلي|العميل|عملائي|أحد\s+عملائي|احد\s+عملائي)" + _NOT_AR_AFTER,
    re.IGNORECASE,
)
# Clients of theirs, or of an owner: "for my clients" is a broker's unless a business owner's words say whose
# (own_customers). Roman Urdu "client" is one or many ("mere client bohat aate hain").
_RU_PLACE = r"(?:parking|jagah|jaga|space|seating|baithne|bethne|waiting|area|sitting|lounge)"
_MINE_MANY = re.compile(
    r"\b(?:for|on\s+behalf\s+of)\s+" + _MINE + r"\s+clients\b" + _NOT_A_NOUN + _TO_COME
    # "mere client ko shop chahiye", "mera client France cluster mein shop dhoond raha hai" (never "mere client ko
    # parking chahiye").
    + r"|\b(?:mere|mera|meri|meray|mery|hamare|hamara|humare|humara|apne|apna|apni|apney)\s+client\b"
    + r"(?!\s+(?:ko|ke\s+liye|k\s+liye|kay\s+liye)\s+" + _RU_PLACE + r"\b)"
    # Arabic "لعملائي" (for my clients); Urdu script and Devanagari "میرے کلائنٹ کو", "मेरे क्लाइंट को".
    + r"|" + _NOT_AR_BEFORE + r"[وف]?لعملائي" + _NOT_AR_AFTER
    + r"|(?:میرے|میرا|ہمارے|ہمارا)\s+کلائنٹ|(?:मेरे|मेरा|हमारे|हमारा)\s+क्लाइंट",
    re.IGNORECASE,
)
# A client in words that are no first person: theirs unless the clause holds a "not" or words about us before it.
# "Looking for a client" seeks one (an owner's tenant), "waiting for a client" awaits one; "parking for client", "a
# discount for client" ask about a client's place or price.
_SEEKS = (
    r"(?<!looking\s)(?<!searching\s)(?<!hunting\s)(?<!seeking\s)(?<!finding\s)(?<!need\s)(?<!needs\s)(?<!want\s)(?<!wants\s)"
    r"(?<!waiting\s)(?<!wait\s)(?<!parking\s)(?<!space\s)(?<!area\s)(?<!seating\s)(?<!seats\s)(?<!room\s)(?<!toilet\s)"
    r"(?<!washroom\s)(?<!lounge\s)(?<!reception\s)(?<!chairs\s)(?<!good\s)(?<!easy\s)(?<!convenient\s)(?<!suitable\s)"
    r"(?<!ideal\s)(?<!enough\s)(?<!discount\s)(?<!discounts\s)(?<!offer\s)(?<!offers\s)(?<!price\s)(?<!prices\s)(?<!rate\s)"
    r"(?<!rates\s)(?<!deal\s)(?<!commission\s)(?<!fee\s)"
)
_FOR_A_CLIENT = re.compile(
    # One client ("for a client", "for client"): "good for clients" or "parking for the clients" is a business's.
    r"\b" + _SEEKS + r"(?:for|on\s+behalf\s+of)\s+(?:(?:a|an|the|one)\s+)?client\b(?!'s\b)" + _NOT_A_NOUN + _TO_COME
    # Arabic "لعميل"; Urdu script and Devanagari: our own for-whom question's words ("کلائنٹ کے لیے", "क्लाइंट के लिए").
    + r"|" + _NOT_AR_BEFORE + r"[و]?(?:لعميل|للعميل|لعميلة)" + _NOT_AR_AFTER
    + r"|کلائنٹ\s*(?:کے|کی)\s*(?:لیے|لئے)|کلائنٹ\s*کیلئے|क्लाइंट\s*(?:के|की)\s*(?:लिए|लिये)",
    re.IGNORECASE,
)
# Roman Urdu "client ke liye", "customer ke liye dekh raha hoon": one or many (never "client ke liye parking chahiye").
_FOR_CLIENTS_RU = re.compile(
    r"\b(?:client|clients|customer|party)\s+(?:ke|k|kay|ki|kai|key)\s*(?:liye|liay|lie|lye|liyay|leye|liya)\b(?!\s+" + _RU_PLACE + r"\b)",
    re.IGNORECASE,
)
# Their whole message is the answer: "Client", "A client", "For client", "Yes, client", "client ke liye".
_ALONE = re.compile(
    r"^[\W_]*(?:(?:yes|yeah|yep|yup|ok|okay|haan|han|ji|jee)[\W_]+)?(?:(?:it\s+is|its|it's)\s+)?(?:for\s+)?(?:a\s+|my\s+|our\s+)?"
    r"(?:client|clients)(?:\s+(?:ke|k|kay)\s+(?:liye|lie|liay|lye))?[\W_]*$"
    r"|^[\W_]*(?:عميل|لعميل|لعميلي|کلائنٹ|क्लाइंट)[\W_]*$",
    re.IGNORECASE,
)
# "Agent" or "Broker" alone: their answer to our for-whom question only (after our price line it may ask for a person).
_ALONE_ROLE = re.compile(
    r"^[\W_]*(?:(?:yes|yeah|yep|yup|ok|okay|haan|han|ji|jee)[\W_]+)?(?:an?\s+)?(?:agent|agents|broker|brokers|realtor)[\W_]*$"
    r"|^[\W_]*(?:وسيط|سمسار|ایجنٹ|بروکر|एजेंट|ब्रोकर)[\W_]*$",
    re.IGNORECASE,
)
# Our for-whom question (rules "for_whom" without its "Thank you!", nudges.FOR_WHOM_QUESTIONS), and any line of ours that
# asks about a client.
_FOR_WHOM = tuple(line.split("!", 1)[1].strip().casefold() for line in rules.LINES["for_whom"].values())
_CLIENT_WORD = re.compile(r"\bclients?\b|عميل|کلائنٹ|क्लाइंट", re.IGNORECASE)

# For myself, in our languages: the answer that makes them the end user (self_words).
_SELF = re.compile(
    r"\bfor\s+(?:my\s*self|myself|my\s+own\s+(?:use|business|shop|self|company|work|purpose)|my\s+business|own\s+use"
    r"|personal\s+use|self\s+use)\b"
    r"|\b(?:i\s*am|i'?m|im)\s+(?:the\s+|an?\s+)?end\s*-?\s*user\b"
    # Roman Urdu "apne liye", "khud ke liye", "shop mere liye hai" (never "apne liye nahi").
    r"|\b(?:apne|apney|apnay|apni|khud\s+(?:ke|k|kay))\s+(?:hi\s+)?(?:liye|liay|lie|lye|liyay)\b(?!\s+(?:nahi|nahin|nhi|nai)\b)"
    r"|\bmere\s+(?:hi\s+)?liye\s+(?:hai|he|h|hy|hi)\b"
    # Urdu script, Devanagari, Arabic: "اپنے لیے", "अपने लिए", "لي شخصياً", "لنفسي".
    r"|(?:اپنے|خود\s+کے)\s+(?:لیے|لئے)(?!\s+نہیں)|(?:अपने|खुद\s+के)\s+(?:लिए|लिये)(?!\s+नहीं)"
    r"|" + _NOT_AR_BEFORE + r"(?:لنفسي|لي\s+شخصيا|لي\s+شخصياً|لي\s+أنا|لي\s+انا|المحل\s+لي)" + _NOT_AR_AFTER,
    re.IGNORECASE,
)
# "For me", "It's for me", "Just for me", "Myself", "لي" as the clause they answer with (never "hold 5 PM for me").
_SELF_ANSWER = re.compile(
    r"^\W*(?:(?:yes|yeah|no|ok|okay|actually|well)\W+)?(?:(?:it'?s|it\s+is|its|this\s+is|the\s+shop\s+is|shop\s+is|is)\s+)?"
    r"(?:just\s+|only\s+|mainly\s+)?for\s+me\b"
    r"|\b(?:it|this|shop|one)(?:'s|\s+is)?\s+(?:just\s+|only\s+)?for\s+me\b"
    r"|^\W*(?:(?:yes|yeah|ok|okay)\W+)?(?:my\s*self|myself|me|personally|personal)\W*$"
    r"|^\W*(?:(?:نعم|ايوه|أيوه)\W+)?(?:لي|شخصيا|شخصياً|شخصي)\W*$",
    re.IGNORECASE,
)

# Words about us: "you" or "your" before the word, in a phrase about us. Never a question mark alone, nor a "you" after
# the word: "Any shop for client?", "Do you have Type 2 for a client", "Do you work with brokers?" are theirs.
_YOUR = r"(?:your|yours|ur|aapka|apka|aapke|apke|aapki|apki|tumhara|tumhare|tumhari)"
_THE_WORD = r"(?:clients?|agents?|brokers?|realtors?|brokerage|agency)"
_ARTICLES = r"(?:(?:also|really|an?|the|one|just|actually)\s+)*"
_ABOUT_US = re.compile(
    # "Who is your client?", "your own agent", "aap ka client".
    r"\b" + _YOUR + r"\s+(?:\w+\s+)?" + _THE_WORD + r"\b"
    + r"|\b(?:aap|ap|tum)\s+(?:ka|ke|ki|k)\s+(?:\w+\s+)?(?:clients?|agents?|brokers?)\b"
    # "Are you an agent?", "you are a broker?", "r u agent", "Are you working as a broker?".
    + r"|\b(?:are|r|were)\s+(?:you|u)\s+" + _ARTICLES + r"(?:" + _KIND + r"\s+){0,2}(?:agents?|brokers?|realtors?)\b"
    + r"|\b(?:(?:you|u)\s+(?:are|r)|you'?re)\s+" + _ARTICLES + r"(?:" + _KIND + r"\s+){0,2}(?:agents?|brokers?|realtors?)\b"
    + r"|\b(?:are|r|do|did)\s+(?:you|u)\s+(?:also\s+)?(?:work|working|act|acting)\s+as\b"
    # Our for-whom question said back: "Are you checking for a client?", "aap kisi client ke liye dekh rahe hain".
    + r"|\b(?:are|r|were)\s+(?:you|u)\s+(?:checking|looking|asking|searching|seeing)\s+for\s+(?:a\s+|the\s+|any\s+|some\s+)?clients?\b"
    + r"|\b(?:aap|ap)\s+(?:kisi\s+)?client\s+(?:ke|k|kay)\s+(?:liye|lie|liay|lye)\s+dekh"
    + r"|\b(?:aap|ap|tum)\s+(?:bhi\s+)?(?:agent|broker|dalal)\s+(?:ho|hain|hai|hn|hen)\b"
    # Arabic: "عميلكم", "أنت وسيط؟", "تبحث عنه لعميل" (our question's words).
    + r"|" + _NOT_AR_BEFORE + r"[وف]?(?:عميلك|عميلكم|عملائك|عملائكم)" + _NOT_AR_AFTER
    + r"|" + _NOT_AR_BEFORE + r"(?:أنت|انت|أنتم|انتم|انتو|حضرتك)\s+(?:وسيط|سمسار|بروكر|وكيل)"
    + r"|تبحث\s+عنه\s+لعميل"
    # Urdu script and Devanagari: "آپ کا کلائنٹ", "آپ ایجنٹ ہیں", "आपका क्लाइंट", "आप एजेंट हैं", our question said back.
    + r"|آپ\s+(?:کا|کے|کی)\s+کلائنٹ|آپ\s+(?:بروکر|ایجنٹ)|آپ\s+(?:کسی\s+)?کلائنٹ\s+(?:کے|کی)\s+(?:لیے|لئے)"
    + r"|(?:आपका|आपके|आपकी)\s+क्लाइंट|आप\s+(?:ब्रोकर|एजेंट)|आप\s+(?:किसी\s+)?क्लाइंट\s+(?:के|की)\s+(?:लिए|लिये)",
    re.IGNORECASE,
)
_WHICH_CLIENT = re.compile(
    r"\b(?:which|what|wht|whose|ur)\s+(?:clients?|agents?|brokers?)\b|\bwho\s+(?:is|are)\s+(?:the|that)\s+clients?\b", re.IGNORECASE
)
# Asking what we meant: "What do you mean, for a client?", "You mean client?", "kya matlab?".
_MEANT = re.compile(r"\b(?:(?:do|did)\s+(?:you|u)\s+mean|you\s+mean|kya\s+matlab)\b", re.IGNORECASE)
# Our word said back alone, asking: "client?", "For a client?", "Agent?".
_ECHO = re.compile(
    r"^[\W_]*(?:for\s+)?(?:a\s+|an\s+|the\s+|my\s+)?(?:client|clients|agent|agents|broker|brokers)\s*[?؟][\W_]*$"
    r"|^[\W_]*(?:عميل|لعميل|وسيط|سمسار|کلائنٹ|ایجنٹ|بروکر|क्लाइंट|एजेंट|ब्रोकर)\s*[?؟][\W_]*$",
    re.IGNORECASE,
)
# A no in the clause: "For myself, not for a client", "I don't have a client", "client ke liye nahi".
_NEGATION = re.compile(
    r"\b(?:not|no|never|nor|neither|without|dont|doesnt|isnt|arent|wasnt)\b|n't\b|\b(?:nahi|nahin|nhi|nai)\b"
    r"|" + _NOT_AR_BEFORE + r"(?:لا|ليس|ليست|مش|مو)" + _NOT_AR_AFTER + r"|نہیں|नहीं",
    re.IGNORECASE,
)
# "No" opening the clause answers our question ("No I am an agent", "No for a client"); "not" stays a no.
_ANSWER_NO = re.compile(r"^\W*(?:no+|nope|nah)\b[\s.!-]*", re.IGNORECASE)
# A clause and the marks that end it (a question when they hold "?" or "؟").
_CLAUSE = re.compile(r"[^.,;:!?؟،\n]+[.,;:!?؟،\n]*")
_ENDS = ".,;:!?؟،"
# The words "client", "agent" or "broker" anywhere (client_about_us).
_MENTION = re.compile(
    r"\b(?:clients?|agents?|brokers?|realtors?|brokerage|agency)\b|عميل|عملاء|وسيط|سمسار|بروكر|کلائنٹ|ایجنٹ|بروکر|क्लाइंट|एजेंट|ब्रोकर",
    re.IGNORECASE,
)

# A business owner speaking of their own customers: serving them, them coming to their place, client meetings.
_BUSINESS_WORDS = (
    r"salon|spa|clinic|restaurant|cafe|café|cafeteria|gym|boutique|showroom|garage|workshop|pharmacy|bakery|laundry"
    r"|barbershop|barber\s+shop|parlou?r|store|business|practice|kitchen|bistro|cent(?:er|re)s?|tailoring|tailors?|supermarket"
    r"|grocery|minimart|printing|institute|academy|nursery|(?<!estate\s)(?<!property\s)(?<!properties\s)agency"
)
_BUSINESSES = r"(?:" + _BUSINESS_WORDS + r")"
_PLACE_WORDS = (
    r"(?:parking|space|area|seating|seats|room|toilet|washroom|lounge|reception|chairs|good|better|best|easy|easier|convenient"
    r"|accessible|comfortable|close|near|nearby|suitable|ideal|enough|reachable|visibility|visible|exposure|access)"
)
_OWN_CUSTOMERS = re.compile(
    r"\b(?:serve|serves|serving|served|service|servicing|attend\s+to|attending\s+to|cater\s+to|catering\s+to|catering\s+for"
    r"|treat|treating|receive|receiving|host|hosting|welcome|welcoming|accommodate|accommodating|entertain|entertaining"
    r"|look\s+after|looking\s+after|take\s+care\s+of|taking\s+care\s+of)\s+(?:to\s+)?(?:(?:all|more|the|my|our|own|regular|loyal)\s+)*"
    r"(?:clients|customers|clientele|patients|guests)\b"
    r"|\b(?:my|our)\s+(?:(?:own|regular|loyal|walk-?in|daily)\s+)?(?:clients|customers|clientele|patients)\s+(?:who\s+|that\s+)?"
    r"(?:(?:can|will|would|usually|always|often|mostly|all|also|then)\s+)?(?:come|comes|coming|came|visit|visits|visiting|walk|walks"
    r"|walking|drop|drops|park|parks|parking|wait|waits|waiting|sit|sits|queue|book|books|order|orders|buy|buys|shop|pay|pays|prefer"
    r"|prefers|like|likes|love|loves|enjoy|enjoys|know|knows|trust|trusts|live|stay|feel|need\s+parking)\b"
    r"|\b(?:clients?|customers?)\s+" + _CLIENT_NOUNS + r"\b"
    r"|\bfor\s+(?:my|our|the)\s+(?:clients|customers)\s+to\s+(?:come|visit|sit|wait|park|meet|relax|enjoy|shop|feel|stay|find|reach|access)\b"
    # "parking for my clients", "reachable for our customers", "good for my clients": theirs ("my", "our") only; "parking
    # for customers" may be a broker's client's.
    r"|\b" + _PLACE_WORDS + r"\s+for\s+(?:my|our)\s+(?:clients|customers)\b"
    r"|\b(?:my|our)\s+" + _BUSINESSES + r"(?:'s|s)?\s+(?:clients|customers|clientele|patients)\b"
    r"|\b(?:clients?|customers?|clientele|patients)\s+(?:of|at|in|from|to)\s+(?:my|our)\s+(?:" + _BUSINESS_WORDS + r"|shop)\b"
    r"|\b(?:come|comes|coming|came|visit|visits|visiting)\s+(?:to|at)\s+(?:my|our)\s+(?:" + _BUSINESS_WORDS + r"|shop)\b"
    r"|\b(?:my|our|own|regular|loyal)\s+(?:customers|clientele)\b"
    # "I have many clients who live in International City".
    r"|\b(?:i|we)\s*(?:have|'ve|got)\s+(?:(?:so\s+)?many|a\s+lot\s+of|lots\s+of|lot\s+of|regular|loyal|some)\s+(?:clients|customers)"
    r"\s+(?:who|that)\s+(?:\w+\s+)?(?:live|lives|living|come|comes|visit|visits|stay|stays|work|works)\b"
    # Roman Urdu: "mere customers aate hain", "mere client bohat aate hain", "mere client IC mein rehte hain", "clients ko
    # serve karna".
    r"|\b(?:mere|meray|hamare|humare|apne|apney)\s+(?:customers?|clients?|grahak)\s+(?:\w+\s+){0,3}?(?:aate|aati|aayenge|aaenge"
    r"|aatay|aaty|ate|rehte|rehti|rahte|jaate)\b"
    r"|\b(?:customers?|clients)\s+(?:ko|ku)\s+(?:serve|service|deal|handle|attend)\b"
    # Arabic: "لخدمة عملائي", "عملائي يأتون", "اجتماعات العملاء", "زبائني", "محل مناسب لعملائي".
    r"|(?:لخدمة|خدمة|استقبال|لاستقبال)\s+(?:عملائي|العملاء|زبائني|الزبائن|عملائنا|زبائننا)"
    r"|(?:عملائي|زبائني|عملائنا|زبائننا)\s+(?:يأتون|ياتون|يجون|يزورون|يحبون|يفضلون|يسكنون)"
    r"|(?:مناسب|مناسبة|قريب|قريبة|سهل|سهلة|مواقف|موقف|باركنج|باركينج)\s+(?:\S+\s+){0,2}?(?:لعملائي|للعملاء|لزبائني|للزبائن|لعملائنا"
    r"|لزبائننا)"
    r"|(?:اجتماعات|اجتماع|مقابلة|مقابلات)\s+(?:العملاء|عملائي|مع\s+العملاء)|زبائني|زبائننا",
    re.IGNORECASE,
)
# Their own business, said with "my clients" (more than one): "I need a shop for my clients, I have a salon".
_A_WORD = r"(?:(?!clients?\b|customers?\b)\w+\s+)?"  # "a travel agency", "my beauty center" (never "my clients business")
_OWN_BUSINESS = re.compile(
    r"\b(?:i|we)\s+(?:have|own|run|operate|manage|got|'ve\s+got)\s+(?:(?:a|an|my|our|the|one|two|2)\s+)?" + _A_WORD + _BUSINESSES + r"\b"
    r"|\b(?:my|our)\s+" + _A_WORD + _BUSINESSES + r"\b",
    re.IGNORECASE,
)
_CLIENTS = re.compile(r"\bclients\b", re.IGNORECASE)

# Family, a friend or a partner (SHOPS_SYSTEM: someone they know can message us; eval shops-rented-licence-no).
_FAMILY = re.compile(
    r"\b(?:my|our)\s+(?:(?:elder|younger|big|little|own|best|close)\s+)?(?:brother|brothers|sister|sisters|cousin|cousins|uncle|uncles"
    r"|aunt|aunts|aunty|auntie|father|dad|daddy|mother|mom|mum|mommy|son|sons|daughter|daughters|wife|husband|nephew|nephews|niece"
    r"|nieces|relative|relatives|family|families|in-?laws?|brother-?in-?law|sister-?in-?law|father-?in-?law|son-?in-?law|friend"
    r"|friends|buddy|partner|partners|business\s+partner|colleague|colleagues|fianc[eé]e?|kids?|children|grandson|granddaughter"
    r"|grandfather|grandmother|parents)\b"
    r"|\b(?:for\s+a|a)\s+(?:friend|relative|family\s+member)\b|\bfriends?\s+of\s+(?:mine|ours)\b"
    # Roman Urdu: "mere bhai ke liye", "mera dost", "bhai ke liye".
    r"|\b(?:mera|mere|meri|meray|apna|apne|apni|hamara|hamare|hamari|humara|humare)\s+(?:bhai|bhaiya|bhaijaan|bhaijan|behan|behen"
    r"|bahen|bahan|abbu|abba|ammi|ammu|walid|walida|beta|beti|bete|chacha|chachu|mamu|mamoo|khala|phuppo|phupho|cousin|dost|doston"
    r"|biwi|wife|shohar|husband|partner|rishtedar|bachay|bache)\b"
    r"|\b(?:bhai|bhaiya|behan|dost|cousin|partner|rishtedar)\s+(?:ke|k|kay|ki)\s*(?:liye|liay|lie|lye)\b"
    # Arabic: "لأخي", "صديقي", "شريكي", "ابن عمي".
    r"|" + _NOT_AR_BEFORE + r"[وف]?ل?(?:أخي|اخي|اخوي|أخوي|أختي|اختي|ابني|إبني|بنتي|ابنتي|زوجتي|زوجي|أبي|ابي|أبوي|ابوي|والدي|والدتي"
    r"|أمي|امي|صديقي|صاحبي|شريكي|قريبي|عائلتي|أهلي|اهلي)" + _NOT_AR_AFTER
    + r"|(?:ابن|ولد|بنت)\s+(?:عمي|خالي)|(?:صديق|قريب)\s+لي"
    # Urdu script and Devanagari.
    r"|(?:میرے|میرا|میری|اپنے|اپنا|اپنی|ہمارے)\s+(?:بھائی|بہن|بیٹے|بیٹا|بیٹی|والد|ابو|امی|دوست|کزن|پارٹنر|بیوی|شوہر)"
    r"|(?:بھائی|دوست|کزن)\s+کے\s+(?:لیے|لئے)"
    r"|(?:मेरे|मेरा|मेरी|अपने|अपना|अपनी|हमारे)\s+(?:भाई|बहन|बेटे|बेटा|बेटी|पिता|पापा|माँ|मां|दोस्त|कज़िन|कजिन|पार्टनर|पत्नी|पति)"
    r"|(?:भाई|दोस्त)\s+के\s+(?:लिए|लिये)",
    re.IGNORECASE,
)


def _words(text) -> str:
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'").split())


def _texts(texts) -> list[str]:
    return [said for said in (_words(text) for text in texts or ()) if said]


def _clauses(text: str) -> list[str]:
    return [clause for clause in _CLAUSE.findall(text) if clause.strip()]


def _question(clause: str) -> bool:
    return "?" in clause or "؟" in clause


def _clause_at(text: str, start: int) -> tuple[str, int]:
    """The clause of ``text`` that holds ``start``, and where ``start`` falls in it."""
    left = max(text.rfind(mark, 0, start) for mark in _ENDS) + 1
    rights = [at for at in (text.find(mark, start) for mark in _ENDS) if at != -1]
    right = min(rights) + 1 if rights else len(text)
    return text[left:right], start - left


def _negated(clause: str, upto: int | None = None) -> bool:
    """A no in the clause, before ``upto`` when given: "not as an agent", "I'm not checking for a client"; a "No" that
    opens it answers our question instead ("No I am an agent")."""
    return bool(_NEGATION.search(_ANSWER_NO.sub("", clause if upto is None else clause[:upto], count=1)))


def about_us(clause: str, upto: int | None = None, *, message: str = "") -> bool:
    """Words about us, never an answer of theirs: "you" or "your" before the word in a phrase about us ("Who is your
    client?", "Are you an agent?", "Are you checking for a client?"; with ``upto``, a phrase that starts before that
    point), "Which client?", or a ``message`` that asks what we meant ("What do you mean, for a client?") or says our word
    back alone ("client?"). A question mark alone, or a "you" after the word, is theirs: "Any shop for client?", "I will
    share with my client and let you know"."""
    for pattern in (_ABOUT_US, _WHICH_CLIENT):
        if any(upto is None or match.start() < upto for match in pattern.finditer(clause)):
            return True
    return bool(message) and (bool(_MEANT.search(message)) or bool(_ECHO.match(message)))


def _hits(pattern, text: str, *, whole_clause: bool = False, about: bool = False) -> bool:
    """A match of the pattern in ``text`` that is theirs: no "not" before it in its clause (in all of the clause with
    ``whole_clause``: "client ke liye nahi"), and, with ``about``, no words about us before it."""
    for match in pattern.finditer(text):
        clause, upto = _clause_at(text, match.start())
        if _negated(clause, None if whole_clause else upto):
            continue
        if about and about_us(clause, upto, message=text):
            continue
        return True
    return False


def _role(text: str) -> bool:
    """Words of theirs as an agent that are no "I am" (_ROLE), never after a no, a fee or a past ("not as an agent",
    "What's the commission as broker?", "I used to work as a broker"), nor about us ("Are you working as a broker?")."""
    for match in _ROLE.finditer(text):
        clause, upto = _clause_at(text, match.start())
        if _negated(clause, upto) or about_us(clause, upto, message=text):
            continue
        if _AS_ROLE.match(text, match.start()) and _NOT_A_ROLE_BEFORE.search(clause[:upto]):
            continue
        return True
    return False


def explicit(texts) -> bool:
    """I am / we are an agent or a broker, in their own words, with no "not" before it (EXPLICIT)."""
    return any(_hits(_EXPLICIT, text) for text in _texts(texts))


def self_words(texts) -> bool:
    """Their words say the shop is for themselves: "For myself", "It's for me", "Myself", "apne liye", "لي شخصياً"
    (never "not for myself", "apne liye nahi", nor "for me" inside another ask: "hold 5 PM for me")."""
    for text in _texts(texts):
        if _hits(_SELF, text):
            return True
        if any(_SELF_ANSWER.search(clause) and not _negated(clause) for clause in _clauses(text)):
            return True
    return False


def told_end_user(answer: dict, known: dict | None) -> str:
    """Why this turn's answer, or what the chat knew before it, says they are the end user: the model's for_client false
    now, or the chat's (SAID_FOR_ME), or the chat knows their business (KNOWN_BUSINESS); '' when nothing does. Their
    client words then never make them a broker, only EXPLICIT does ("I have a client at 3" is a salon owner's)."""
    known = known or {}
    if answer["facts"].get("for_client") is False or known.get("for_client") is False:
        return SAID_FOR_ME
    if known.get("business_activity"):
        return KNOWN_BUSINESS
    return ""


def _one_client(texts) -> bool:
    """Someone else's client named in their words, theirs (no "not" before it, no words about us): "my client needs",
    "for a client", "I have a client looking for a shop", "my customer needs", or "client" as their whole answer."""
    for text in texts:
        if _hits(_MINE_ONE, text) or _hits(_FOR_A_CLIENT, text, whole_clause=True, about=True):
            return True
        if not _question(text) and _ALONE.match(text):
            return True
    return False


def _many_clients(texts) -> bool:
    """Clients of theirs that may be an owner's own: "for my clients", Roman Urdu "mere client", "client ke liye"."""
    return any(_hits(_MINE_MANY, text) or _hits(_FOR_CLIENTS_RU, text, whole_clause=True, about=True) for text in texts)


def asked_for_whom(our_last) -> bool:
    """Our last message asked who the shop is for (rules "for_whom", the nudge that asks it again, or the model's words
    around it), or asked about a client."""
    body = " ".join(str(our_last or "").split()).casefold()
    return any(question in body for question in _FOR_WHOM) or (_question(body) and bool(_CLIENT_WORD.search(body)))


def own_customers(texts) -> bool:
    """A business owner speaking of their own customers, clause by clause: serving them ("I need a shop to serve my
    clients"), them coming to their place ("my clients come to my salon"), client meetings, their parking ("Parking for
    my clients is important"), or "my clients" with a business of their own ("for my clients, I have a salon", "I have a
    travel agency ... for my clients"). Never in a burst that names someone else's client ("My client needs a shop with
    parking for customers": a broker describing his client's business). Their client words of many then never make
    them a broker (declares)."""
    texts = _texts(texts)
    if _one_client(texts):
        return False
    if any(_OWN_CUSTOMERS.search(clause) for text in texts for clause in _clauses(text)):
        return True
    said = " ".join(texts)
    return bool(_OWN_BUSINESS.search(said) and _CLIENTS.search(said))


def declares(texts, *, explicit_only: bool = False, our_last: str = "") -> bool:
    """Their own words this burst say they are an agent or a broker, or source the shop for a client.

    I am / we are an agent or a broker (EXPLICIT) always counts. With ``explicit_only`` (a person holds the chat, or the
    answer or the chat says they are the end user: told_end_user), or when the burst says "for myself" (self_words),
    nothing else does. Otherwise: their other words as one (_ROLE: "Broker here", "As a broker", "This is Neeta from AR
    Properties"); someone else's client named (_MINE_ONE, _FOR_A_CLIENT, _ALONE); clients that may be an owner's own,
    unless a business owner's words say whose (_MINE_MANY, _FOR_CLIENTS_RU, own_customers); "Agent" or "Broker" alone, as
    the answer to our for-whom question only (``our_last``: asked_for_whom)."""
    texts = _texts(texts)
    if explicit(texts):
        return True
    if explicit_only or self_words(texts):
        return False
    if any(_role(text) for text in texts) or _one_client(texts):
        return True
    if _many_clients(texts) and not own_customers(texts):
        return True
    return asked_for_whom(our_last) and any(not _question(text) and _ALONE_ROLE.match(text) for text in texts)


def family(texts) -> bool:
    """Family, a friend or a partner named in their words ("for my brother", "my friend needs one", "mere bhai ke liye")."""
    return any(_FAMILY.search(text) for text in _texts(texts))


def client_about_us(texts) -> bool:
    """"client", "agent" or "broker" is said only in words about us ("Who is your client?", "Are you an agent?", "Which
    client?", "What do you mean, for a client?"), and no client of theirs is named."""
    texts = _texts(texts)
    said = [(text, clause) for text in texts for clause in _clauses(text) if _MENTION.search(clause)]
    if not said or any(_hits(_MINE_ONE, text) or _hits(_MINE_MANY, text) for text in texts):
        return False
    return all(about_us(clause, message=text) for text, clause in said)


def end_user(texts) -> str:
    """Why the model's facts.for_client alone makes no broker of them in this burst: OWN_CUSTOMERS, FAMILY, SELF or
    ABOUT_US; '' when nothing in their words says so."""
    if own_customers(texts):
        return OWN_CUSTOMERS
    if family(texts):
        return FAMILY
    if self_words(texts):
        return SELF
    if client_about_us(texts):
        return ABOUT_US
    return ""


def newly(answer: dict, known: dict | None) -> bool:
    """The model recorded facts.for_client true in this answer, and the chat did not know it before (``known``)."""
    return answer["facts"].get("for_client") is True and (known or {}).get("for_client") is not True


def backstop(answer: dict, known: dict | None, texts, *, labelled=False, held: bool = False, our_last: str = "") -> str:
    """A shops answer right after the model (live and in the eval, after engine.untag_need): handed over as a broker
    (REASON) when their own words this burst declare it (WORDS; over a handover of the model's too, but KEEPS, while
    OVER_WEAKER), or the model recorded facts.for_client true this turn and handed the chat to nobody (FACTS; never when
    end_user reads them as one). Returns what handed it over, else ''.

    ``known``: the chat's facts before this turn; ``texts``: their words in this burst (engine.need_texts);
    ``held``: a person holds the chat (state.handed_over_at): only EXPLICIT words then, never the model's for_client
    ("I'm outside, agent not picking up" is our agent); ``our_last``: our last message (a bare "Agent" answers our
    for-whom question only); ``labelled``: the chat carries the Broker label already (a bool, or a callable asked only
    when the backstop would act): nothing then, the chat is the agents'. The answer then holds the handover,
    facts.for_client true and ``answer["broker_backstop"]``; engine.settle labels and pauses it with the hand-off line,
    as for the model's tag. A taken slot it offered is none: code offers none around a handover (engine._code_may_act)."""
    if not BACKSTOP or answer["opt_out"] != "none":
        return ""
    handover = answer["handover"]
    if handover["needed"] and handover["reason"] in (REASON, *KEEPS):
        return ""
    only_explicit = bool(held) or bool(told_end_user(answer, known))
    if declares(texts, explicit_only=only_explicit, our_last=our_last) and (not handover["needed"] or OVER_WEAKER):
        by = WORDS
    elif not held and not handover["needed"] and newly(answer, known) and not end_user(texts):
        by = FACTS
    else:
        return ""
    if labelled() if callable(labelled) else labelled:
        return ""
    answer["handover"] = {"needed": True, "reason": REASON}
    answer["facts"]["for_client"] = True
    answer.pop("slot_taken", None)
    answer["broker_backstop"] = by
    return by
