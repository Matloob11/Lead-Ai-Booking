"""What a shops chat records about the customer goes on the record only when it is theirs (launch review 15, 26).

- facts.notes are the questions our agent answers at the viewing: the alerts and the Bitrix comments print them
  as "Questions for the viewing". Live, the model filled them with its own discovery questions ("What size do you
  need?", "size needed; budget; licence kind": chats 49, 78, 88, 96, 100 and 119), our own sentences ("Is the
  shop for yourself, or are you checking for a client?" in chats 42, 52, 98 and 114, "Currently only shops for
  rent, not sale" in 42) and the prompt's example list ("service charge; DEWA; parking; fit-out": chats 44, 59,
  62 and 88, none of which asked), while chat 95 lost four of its nine real questions to a cap of five.
  ``their_notes`` keeps a note only when it is a question of theirs:
  1. never one put to the customer ("is the shop for yourself", "suitable for your business", "are you checking
     for a client", "do you want to buy"); one of theirs to us stays ("What is your commission?");
  2. never one that is only our discovery list (the business, the size, the budget, the licence, when to open,
     who the shop is for) or says nothing;
  3. never the prompt's examples (service charge, DEWA, chiller, parking, fit-out, the unit) unless their own
     words name that thing, in any of our languages;
  4. never a sentence of ours copied back, mostly in words of ours they never wrote (read when they write
     English letters).
  ``own_notes`` is 1 and 2 alone (no words needed): the notes a chat holds already, and what alerts and comments
  print, are read through it.
- facts.budget_aed equal to one of our own figures (a type's "from" price, its rents) is theirs only when they
  wrote it ("33k" is): chat 62's alert said "Budget (AED): 48000", our Type 2 price, which he never gave. Nor is
  one only the old lead's CRM notes hold (``budget_of_notes``; the launch gate's review: the model wrote the notes'
  "Budget around 40k a year" as theirs, and the next turn said "With your budget of AED 40,000 a year" back).
- facts.business_activity is a business: never a home they want ("apartment studio", "room", "studio" went to the
  lead's Business activity field in chats 44, 49, 57 and 68) and never a sentence ("Is a studio apartment with
  balcony suitable for your business?").
- Their must-answer questions are never lost from the notes (``their_questions``; the launch gate's eval
  shops-nine-questions-noted-95 lost "Dubai Municipality approval for food establishment" in both runs): each
  clause of theirs that asks one (people.asked_topics: gas, NOC, Municipality approval, Ejari, the total upfront
  amount, ...) and that no note restates is added to facts.notes in their own words.

Plain functions on plain data: engine.settle runs ``settle`` on every shops answer, live and in the eval.
"""

from __future__ import annotations

import re

from . import filters, needs

# The guards, one constant each: notes that are theirs only, a budget of ours never theirs unless they wrote it, their
# must-answer questions noted in their own words when the model's notes miss one, a budget only the old lead's CRM notes
# hold never theirs.
NOTES_THEIRS_ONLY = True
BUDGET_THEIRS_ONLY = True
THEIR_QUESTIONS_NOTED = True
BUDGET_NOT_FROM_NOTES = True
# A business activity of more words than this is a sentence, not a business.
ACTIVITY_WORDS_MAX = 12

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\d+", re.UNICODE)
# Words that carry no question of their own.
_STOP = frozenset(
    """
    a an the of for to in on at by with and or but is are was were be been being do does did done have has had
    it its this that these those there their them they he she his her we our us i me my mine you your yours yourself
    u ur what which who whom whose when where why how much many any some all more most no not yes
    can could will would shall should may might must please kindly also just only about if as so than then
    shop shops one ones need needed needs needing want wants wanted require required requires
    customer customers client question questions ask asked asking details detail info information
    """.split()
)
# Our own discovery list (SHOPS_SYSTEM's DISCOVERY and FOR WHOM): what we ask them, never a question of theirs.
_DISCOVERY = frozenset(
    """
    business businesses activity activities trade size sizes sqft sq ft square feet foot area budget budgets yearly annual
    licence license licences licenses licensing licenced licensed kind type ded trakhees new opening open start starting
    launch myself yourself himself herself themselves checking broker agent purpose buy buying purchase purchasing rent
    renting lease leasing
    """.split()
)
# Put to the customer, never by them: "is the shop for yourself", "suitable for your business", "are you checking
# for a client", "do you want to buy". A question of theirs to us says "your" too ("What is your commission?",
# "Where is your office?", "Can you send the video?", "Do you have parking?"): those stay.
_TO_THEM = re.compile(
    r"\byourself\b|\byourselves\b"
    r"|\byour\s+(?:own\s+)?(?:business|activity|activities|budget|licen[cs]e|trade|size|requirements?|needs?|plans?|company|brand"
    r"|clients?|customers?)\b"
    r"|\b(?:are|do|did|will|would)\s+(?:you|u)\s+(?:need|want|require|prefer|plan|planning|looking|checking|interested|already)\b",
    re.IGNORECASE,
)
# The prompt's own example list, and how a customer names each in our languages.
_EXAMPLES = (
    (
        re.compile(r"service\s*charges?|service\s*fees?|maintenance\s*(?:fees?|charges?)", re.IGNORECASE),
        re.compile(r"service\s*(?:charge|fee)|maintenance|رسوم\s*الخدمة|سروس\s*چارج|सर्विस\s*चार्ज|मेंटेनेंस", re.IGNORECASE),
    ),
    (
        re.compile(r"\bdewa\b|electricity|water\s*(?:bill|connection)", re.IGNORECASE),
        re.compile(r"\bdewa\b|electric|power|water|كهرباء|ماء|ديوا|بجلی|پانی|बिजली|पानी", re.IGNORECASE),
    ),
    (
        re.compile(r"\bparking\b", re.IGNORECASE),
        re.compile(r"\bpark(?:ing)?\b|موقف|مواقف|باركن|پارکنگ|पार्किंग", re.IGNORECASE),
    ),
    (
        re.compile(r"\bfit\s*-?\s*outs?\b|\bfitout\b", re.IGNORECASE),
        re.compile(r"\bfit\s*-?\s*outs?\b|\bfitout\b|fitting|interior|decor|renovat|تجهيز|ديكور|فٹ\s*آؤٹ|फिट\s*आउट|इंटीरियर", re.IGNORECASE),
    ),
    (
        re.compile(r"\bchillers?\b", re.IGNORECASE),
        re.compile(r"chiller|\ba\s*/?\s*c\b|air\s*-?\s*con|cooling|تكييف|تبريد|اے\s*سی|एसी", re.IGNORECASE),
    ),
    (
        # "the exact unit", as the prompt had it ("unit availability" is their "is a shop free?" said our way: it stays).
        re.compile(r"\b(?:exact|specific|which)\s+units?\b|\bunit\s*(?:no\.?|number)\b", re.IGNORECASE),
        re.compile(r"\bunits?\b|which\s+(?:shop|one|building)|exact|رقم\s*المحل|وحدة|یونٹ|यूनिट", re.IGNORECASE),
    ),
)
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def _words(text: str) -> list[str]:
    return [word.casefold().replace("’", "'") for word in _WORD.findall(str(text or ""))]


def _content(text: str) -> set[str]:
    """The note's own words: no stop words, no single letters."""
    return {word for word in _words(text) if word not in _STOP and (len(word) > 1 or word.isdigit())}


def _latin(text: str) -> bool:
    """Most of these letters are English letters (the words can be compared with an English note)."""
    letters = _LETTER.findall(str(text or ""))
    return bool(letters) and len(_ASCII_LETTER.findall(str(text or ""))) >= 0.6 * len(letters)


def to_them(note: str) -> bool:
    """A question put to the customer (ours), never one of theirs."""
    return bool(_TO_THEM.search(str(note or "")))


def discovery_only(note: str) -> bool:
    """The note is our discovery list and nothing else ("size needed", "budget", "licence kind", "What business
    the shop is for?"), or says nothing at all."""
    return _content(note) <= _DISCOVERY


def own_notes(notes) -> list[str]:
    """The notes that may be the customer's, read without their words (rules 1 and 2 of the module's list)."""
    if not NOTES_THEIRS_ONLY:
        return list(notes) if isinstance(notes, list) else notes
    if not isinstance(notes, list):
        return notes  # a general chat's notes are text, never the shops list
    return [note for note in notes if str(note or "").strip() and not to_them(note) and not discovery_only(note)]


def _examples_theirs(note: str, theirs: str) -> bool:
    """Every one of the prompt's examples the note names is named in their own words too."""
    for in_note, in_their_words in _EXAMPLES:
        if in_note.search(note) and not in_their_words.search(theirs):
            return False
    return True


def _copied_from_us(note: str, theirs: str, ours) -> bool:
    """The note is a sentence of ours copied back: all its words are in one sentence of ours, and most of them in
    nothing they wrote ("Currently only shops for rent, not sale" after our "Currently, we only have shops available
    for rent, not for sale."); a question of theirs we said back in a word of ours stays (chat 59's "rent security
    deposit"). Read only when they write English letters, so the words compare."""
    words = _content(note)
    if not words or not _latin(theirs):
        return False
    said = set(_words(theirs))
    missing = words - said
    if len(missing) * 2 <= len(words):
        return False
    for message in ours or ():
        for sentence in filters.split_sentences(str(message or "")):
            if words <= set(_words(sentence)):
                return True
    return False


def their_notes(notes, theirs, ours=()) -> list[str]:
    """The notes that are the customer's own questions (all four rules). ``theirs``: their words in the chat (the
    burst too, voice notes as heard), ``ours``: our messages (the assistant's and the campaign's)."""
    if not NOTES_THEIRS_ONLY or not isinstance(notes, list):
        return notes
    said = " ".join(str(text or "") for text in (theirs or ()))
    kept = []
    for note in own_notes(notes):
        text = str(note)
        if not _examples_theirs(text, said) or _copied_from_us(text, said, ours):
            continue
        kept.append(note)
    return kept


# A word of a note matches a word of their question by its first letters ("approval" is "approved", "installation"
# "installed").
_STEM = 5
_VOICE = "[voice note] "
# What opens a clause of a list ("1)", "-", "•"): no part of the question (people._CLAUSE takes "1. " off already).
_LIST_MARK = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[-*•])\s+")


def _stems(words) -> set[str]:
    return {word[:_STEM] for word in words}


def _restates(note: str, clause: str) -> bool:
    """The note says the clause in fewer words: half of its own words or more are the clause's ("Dubai Municipality
    approval for food establishment" for "Can this exact unit be approved by Dubai Municipality for a food
    establishment?")."""
    mine = _stems(_content(note))
    return bool(mine) and 2 * len(mine & _stems(_words(clause))) >= len(mine)


def _spoken(texts) -> list[str]:
    """Their words as they wrote or said them: a voice note's transcript, never a tap, a photo or a sticker."""
    out = []
    for text in texts or ():
        text = str(text or "").strip()
        if text.startswith(_VOICE):
            text = text[len(_VOICE):]
        elif text.startswith("["):
            continue
        if text:
            out.append(text)
    return out


def their_questions(notes, texts) -> tuple[list[str], list[str]]:
    """(the notes with their must-answer questions that no note holds, what was added). Each clause of their words
    (``texts``: this burst's) that asks a must-answer topic (people.asked_topics) is a question for our agent; one that
    no note restates (_restates), nor names every topic of (people.names_topic), is added in their own words, cleaned
    as the schema cleans a note. The model's own notes stay as they are."""
    from . import people, schema

    out = [str(note) for note in notes or () if str(note or "").strip()] if isinstance(notes, list) else []
    if not THEIR_QUESTIONS_NOTED:
        return out, []
    added: list[str] = []
    for clause, topics in people.asked_topics(_spoken(texts)):
        note = schema.clean_note(_LIST_MARK.sub("", clause))
        if not note or note.casefold() in {have.casefold() for have in out}:
            continue
        if any(_restates(have, clause) or all(people.names_topic(have, topic) for topic in topics) for have in out):
            continue
        out.append(note)
        added.append(note)
    # A numbered list of questions ("1. Can the landlord provide an NOC? 2. ... 5. Can preparation and hand-wash sinks be
    # installed?"): each numbered clause that asks something is one of their questions whatever its topic, so one no note
    # restates is noted in their words (the 2e real-model gate, round 15: chat 95's nine questions kept eight in one run).
    for clause in _numbered_questions(_spoken(texts)):
        note = schema.clean_note(clause)
        if not note or note.casefold() in {have.casefold() for have in out}:
            continue
        if any(_restates(have, clause) for have in out):
            continue
        out.append(note)
        added.append(note)
    return out, added


_NUMBERED = re.compile(r"(?:^|\n)\s*\(?(\d{1,2})[.)]\s+([^\n]+)")


_QUESTION_OPENS = re.compile(
    r"^(?:can|could|is|are|was|were|will|would|do|does|did|how|what|which|when|where|who|whom|whether|any|should|may|shall"
    r"|kya|kia|kitna|kitni|kab|hal|هل|كم|متى|کیا|کتنا|کب|क्या|कितना|कब)\b",
    re.IGNORECASE,
)


def _asks(clause: str) -> bool:
    """A numbered line that asks: it ends with a question mark, or opens with a question word ("Can the landlord provide
    an NOC"); "My shop is small" asks nothing, whatever people._ASKS reads into its "is"."""
    text = " ".join(str(clause or "").split())
    return text.endswith(("?", "؟")) or bool(_QUESTION_OPENS.match(text))


def _numbered_questions(texts) -> list[str]:
    """The clauses of a numbered list in their words that ask something (_asks), in order; [] unless the list has three
    or more numbered lines (a bare "1." in a sentence is no list)."""
    out: list[str] = []
    for text in texts or ():
        found = [(int(number), clause.strip()) for number, clause in _NUMBERED.findall(str(text or ""))]
        if len(found) < 3:
            continue
        out += [clause for _number, clause in found if clause and _asks(clause)]
    return out


def our_figures(shops_facts) -> set[int]:
    """Our own money figures: each type's rents and "from" price (SHOP FACTS)."""
    from . import shops

    out: set[int] = set()
    for shop in shops.types_of(shops.facts_of(shops_facts)):
        out |= {shop.rent_from, shop.rent_to, shop.cheapest}
    return out


def budget_of_ours(budget, theirs, shops_facts) -> bool:
    """facts.budget_aed is one of our own figures and their words never gave it (chat 62's 48000)."""
    if not BUDGET_THEIRS_ONLY or isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        return False
    value = int(round(budget))
    if value not in our_figures(shops_facts):
        return False
    said = {number for number, _ in filters.numbers_in(" ".join(str(text or "") for text in (theirs or ())))}
    return value not in said


def budget_of_notes(budget, theirs, notes) -> bool:
    """facts.budget_aed is a figure of the old lead's CRM notes ("Budget around 40k a year": 40000) that their words in
    this chat never gave: the notes' own, never a budget they gave us (lead_history: the notes are never quoted)."""
    if not BUDGET_NOT_FROM_NOTES or not notes or isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        return False
    value = int(round(budget))
    if value not in {number for number, _ in filters.numbers_in(str(notes))}:
        return False
    said = {number for number, _ in filters.numbers_in(" ".join(str(text or "") for text in (theirs or ())))}
    return value not in said


# How a clause opens, never a business: a question word, a yes or no, someone doing something ("I want ...", "we sell
# ..."). "My clothes shop" is a business.
_SENTENCE_START = re.compile(
    r"^\s*(?:is|are|do|does|did|can|could|will|would|should|what|which|how|why|where|when|please|kindly|yes|no|not)\b"
    r"|^\s*(?:i'm|im|we're|it's|there\s+(?:is|are))\b"
    r"|^\s*(?:i|we|they|he|she)\s+(?:am|are|is|was|want|wants|need|needs|have|has|will|would|sell|run|do|did|plan|am\s+looking)\b",
    re.IGNORECASE,
)


def is_sentence(text: str) -> bool:
    """A sentence, not a business ("Is a studio apartment with balcony suitable for your business?", "I want a shop
    for my clothes, can you help?"): a question, two sentences, one that opens like a clause, or too many words."""
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if any(mark in value for mark in filters.QUESTION_MARKS) or re.search(r"[.!]\s+\S", value):
        return True
    return bool(_SENTENCE_START.match(value)) or len(value.split()) > ACTIVITY_WORDS_MAX


def is_business(text: str) -> bool:
    """A business activity: never a home they want (a studio, a room, a flat, a BHK: needs.detect) nor a sentence."""
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if is_sentence(value):
        return False
    need = needs.detect([value])
    return need is None or need.kind != needs.HOME


def settle(answer: dict, earlier, new_texts, shops_facts=None, *, crm_notes: str = "") -> list[str]:
    """A shops answer's facts with only what is theirs (engine.settle, live and in the eval, before code adds its
    own notes): their notes, a budget of theirs (never one of our figures, nor one only the old lead's ``crm_notes``
    hold), a business; and their must-answer questions this burst that the notes miss, in their own words
    (their_questions; ``answer["notes_added"]``). Returns what was dropped ("notes", "budget", "business_activity"),
    for the turn's log."""
    facts = answer.get("facts")
    if not isinstance(facts, dict):
        return []
    theirs = [text for author, text in earlier or () if author == "customer"] + list(new_texts or ())
    # Our messages, and this answer's own reply: a note that restates what the model says now ("Currently only shops for
    # rent, not sale", with the claim settle then cuts from the reply) is ours, never their question (review 2d).
    ours = [text for author, text in earlier or () if author in ("assistant", "campaign")] + [str(answer.get("reply") or "")]
    dropped = []
    notes = facts.get("notes")
    if isinstance(notes, list) and notes:
        kept = their_notes(notes, theirs, ours)
        if kept != notes:
            facts["notes"] = kept
            dropped.append("notes")
    if isinstance(facts.get("notes"), list):
        # Their must-answer questions this burst, in their own words, where the model's notes (theirs only) miss one.
        noted, added = their_questions(facts["notes"], new_texts)
        if added:
            facts["notes"] = noted
            answer["notes_added"] = added
    if budget_of_ours(facts.get("budget_aed"), theirs, shops_facts) or budget_of_notes(facts.get("budget_aed"), theirs, crm_notes):
        facts["budget_aed"] = None
        facts["budget_basis"] = None
        dropped.append("budget")
    activity = facts.get("business_activity")
    if activity and not is_business(activity):
        facts["business_activity"] = None
        dropped.append("business_activity")
    return dropped
