"""A buyer's 5-minute call with our sales team (batch 2e slice C; spec §3.3; board T94, C40; Q32, Q39, Q40).

A buyer of a studio or a one-bedroom in International City (the sale track, tracks.SALE) may book a 5-minute call with our
sales team as they book an office meeting: the bot books it in a slot of the call pool and says so, and any agent takes it
from the Lead AI screen (the desk lane's I'll call). Nobody is named (Q30), no Google Meet, link or e-mail (T102 later), and
no phone number is given (Q38): our team calls them on this number.

- **The pool** (``taken``): every other chat's open call with a time (a confirmed call, or one held while we ask the full
  name: ``details.track`` "sale"). One call per 30-minute slot, in office hours (Monday to Saturday, 10:00 to the last start
  at 19:30, closed dates out: hours.free_slots), and it takes no office slot: a call and a visit may share a half hour
  (Q40). A shops chat's tentative call request (2d's call_requested) carries no track, never confirms, and holds nothing.
- **The booking** (engine): the model records a call at place "call", which engine.check_proposal takes on the sale track
  only (``places``: PLACES there, OFFICE_ONLY everywhere else) and checks against this pool; a time another buyer holds is
  refused with the two nearest free call slots. Their own words for a call with a day and an hour ("can we do a call at 5")
  book it too (sales.call_step), and a call asked for with no time gets two free call slots, never 2d's call_requested
  handover: a booked call is no handover, and the bot keeps answering the chat.
- **The row** (``mark``): place "call" and ``details.track`` "sale", kept when the details are written again from the facts
  (``kept_details``): the pool, the desk's Today list and its -15 / +10 minute alerts, the reminder and the CRM read them.
- **Bitrix** (``booking_fields``): the C9 booking through the Lead fields tool with C40's Online mode (43) and the to-do
  subject "Sales call", the to-do owned by 2311 (Q22); its move and its cancel name the same subject, so a person's own
  "Viewing/Meeting" to-do is never moved or closed for it (``todo_subject``).
- **The alert** (``alert``): a high-priority "Sales call: {name}, {when}" with "Take it on the Lead AI screen, then
  call them on +{number}." to the chat's people (alerts.recipients).
- **The reminder** (``reminder_text``, ``template_place``): free-form inside the window ("... your 5-minute call with our
  sales team today at {time}. We'll call you on this number."), else the approved meeting reminder with {{3}} "this number
  (our team will call you)"; no new template. Its "On My Way" reads as ready for the call (``tap_line``), and "Need to
  Reschedule" gets two free call slots (taps).

Plain functions (the eval runs the same ones), but for ``taken``, which reads the open calls.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from ..models import LeadAiAppointment
from . import hours

PLACE = LeadAiAppointment.Place.CALL  # "call"
OFFICE = LeadAiAppointment.Place.OFFICE  # "office"
TRACK = "sale"  # tracks.SALE: the only track that books a call (details.track on the row)
MINUTES = 5
# What a turn may book (engine.check_proposal's ``places``): the sale track an office meeting or a call, every other one
# (a shop, rent, other, a general chat) an office visit only, as before.
PLACES = (OFFICE, PLACE)
OFFICE_ONLY = (OFFICE,)
# C40 (board, 2026-10-16): Mode of Meeting Online is 43 (Offline 42, crm.MODE_OFFLINE), and the booking's to-do is "Sales
# call" for a call ("Viewing/Meeting" for a visit, crm.TODO_SUBJECT), its owner 2311 either way (Q22).
MODE_ONLINE = 43
TODO_SUBJECT = "Sales call"
# What the approved meeting reminder's {{3}} ("... at {{3}}") says for a call outside the window (spec §3.3.7).
TEMPLATE_PLACE = "this number (our team will call you)"
# Q40 (Matloob, 2026-10-17): a 5-minute call keeps its own pool and takes no office slot (engine.check_proposal,
# engine._slot_gone). False would check a call against the office's visits instead.
OWN_POOL = True

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


# Which turns book a call -------------------------------------------------------------------------------------------


def places_for(track: str) -> tuple:
    """What a turn of this track may book: an office meeting or a call on the sale track, else an office visit."""
    return PLACES if track == TRACK else OFFICE_ONLY


def allowed(place, places) -> bool:
    """A call this turn may book (the sale track): engine.check_proposal takes it instead of refusing it as not_office,
    and engine._shape leaves its confirm alone instead of making it 2d's call_requested handover."""
    return place == PLACE and PLACE in tuple(places or ())


def is_sales_call(appointment) -> bool:
    """A sales call's row: place "call", confirmed (only the sale track ever confirms one) or marked with the sale track
    (a call held while we ask the full name, a cancelled or past one). A shops chat's tentative call request is none."""
    if appointment is None or getattr(appointment, "place", "") != PLACE:
        return False
    return appointment.status == LeadAiAppointment.Status.CONFIRMED or (appointment.details or {}).get("track") == TRACK


# The pool ---------------------------------------------------------------------------------------------------------


def taken(conversation, now=None) -> list:
    """The starts of every OTHER chat's open sales call with a time: the call slots that are no longer free (one call per
    slot, its own pool: Q40). An office visit takes none of them, and a call takes no office slot (engine.taken_slots)."""
    now = now or timezone.now()
    rows = (
        LeadAiAppointment.objects.filter(
            status__in=LeadAiAppointment.OPEN,
            place=PLACE,
            starts_at__gte=now - hours.SLOT,
            starts_at__lte=now + hours.MAX_AHEAD + dt.timedelta(days=1),
        )
        .exclude(conversation=conversation)
        .only("status", "place", "details", "starts_at")
    )
    return [row.starts_at for row in rows if is_sales_call(row)]


def free(now, closed_dates=(), taken=(), *, count: int = hours.SLOTS_SHOWN) -> list:
    """The next free call slots, an hour apart (hours.spaced), as the model reads them (CALL SLOTS)."""
    every = hours.free_slots(now, closed_dates, taken, count=count * 4)
    return hours.spaced(every, count=count)


def offer(now, closed_dates=(), taken=(), *, day=None, avoid=(), after=None) -> list:
    """The two free call slots code offers (hours.offer_pair on the call pool)."""
    return hours.offer_pair(now, closed_dates, taken, day=day, avoid=avoid, after=after)


def nearest(start, now, closed_dates=(), taken=()) -> list:
    """The two free call slots nearest a taken one (hours.nearest_free on the call pool)."""
    return hours.nearest_free(start, now, closed_dates, taken)


def slots_line(now, closed_dates=(), taken=()) -> str:
    """The context's CALL SLOTS line on the sale track (spec §1.3; the residential context carries it)."""
    shown = free(now, closed_dates, taken)
    listed = "; ".join(hours.slot_line(slot, now) for slot in shown) or "none in the next three weeks"
    return (
        f"CALL SLOTS (a {MINUTES}-minute call with our sales team, one call per half hour; it takes no office slot; offer two "
        f"of these, the system books the one they pick): {listed}"
    )


def pool(call: bool, office_taken, call_taken):
    """The taken slots a booking is checked against: a call's own pool (Q40), a visit's the office's."""
    return call_taken if call and OWN_POOL else office_taken


def needs_pin(answer: dict) -> bool:
    """Our office's pin follows a booking (engine): never a call's, which happens on this number."""
    return (answer.get("appointment") or {}).get("place") != PLACE


# The row ----------------------------------------------------------------------------------------------------------


def mark(row) -> None:
    """A sales call's row: place "call" and details.track "sale" (the pool, the desk, the reminder and the CRM read them)."""
    row.place = PLACE
    row.details = {**(row.details or {}), "track": TRACK}


def kept_details(details: dict, row) -> dict:
    """The details written again from the chat's facts (engine._apply), keeping a sales call's mark and a time's hold for
    the full name (sales.mark_hold): the pool, the desk and the full-name gate read them."""
    details = dict(details or {})
    if row is not None and is_sales_call(row):
        details["track"] = TRACK
    if row is not None and row.status == LeadAiAppointment.Status.TENTATIVE and (row.details or {}).get("held_for_name"):
        details["held_for_name"] = True
    return details


# Bitrix (C40) -----------------------------------------------------------------------------------------------------


def booking_fields(appointment, event: str) -> dict:
    """What a sales call adds to the Lead fields tool's booking (crm.booking_body): the to-do subject "Sales call" for
    every event (its move and its cancel touch only that to-do), and Mode Online for a booking or a move; {} for a visit."""
    if not is_sales_call(appointment):
        return {}
    fields = {"todo_subject": TODO_SUBJECT}
    if event != "cancelled":
        fields["mode"] = MODE_ONLINE
    return fields


def todo_subject(appointment, default: str) -> str:
    """The subject of the booking's own to-do (tasks._book reads the lead's open to-dos of it): "Sales call" for a call."""
    return TODO_SUBJECT if is_sales_call(appointment) else default


# The alert --------------------------------------------------------------------------------------------------------


def alert(conversation, appointment, event: str, name: str, details: list, *, stamp: str, crm_url: str = "") -> bool:
    """A sales call's alert (engine.appointment_alert asks first), True when it raised one: booked or moved (spec §3.3.4),
    a high-priority "Sales call: {name}, {when}" with "Take it on the Lead AI screen, then call them on +{number}."; held
    while we ask the full name, its time noted. The dedupe keys are appointment_alert's ("booked:<pk>:<revision>"), so the
    CRM sync raising it again reaches only who did not have it. Any other event of a call (a cancel, a tap) is the visit's."""
    from . import alerts

    if not is_sales_call(appointment) or event not in ("confirmed", "rescheduled", "tentative") or appointment.starts_at is None:
        return False
    who = name or "A Lead AI customer"
    number = conversation.contact.wa_id
    when = hours.describe(appointment.starts_at)
    if event == "tentative":
        alerts.raise_alert(
            kind="tentative",
            conversation=conversation,
            appointment=appointment,
            title=f"{who}: sales call held, {when}",
            text="\n".join(
                [f"{who} (WhatsApp +{number})", *details, f"Call held for: {when}",
                 "Not booked yet: the assistant asked for their full name first, and books it when they give it."]
            ),
            dedupe_key=f"tentative:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
        return True
    moved = event == "rescheduled"
    lines = [
        f"{who} (WhatsApp +{number})",
        *details,
        f"Call: {when} ({MINUTES} minutes, our sales team calls them)",
        f"Take it on the Lead AI screen, then call them on +{number}.",
        "Moved by the customer with the Lead AI assistant." if moved else "Booked by the Lead AI assistant.",
    ]
    alerts.raise_alert(
        kind="rescheduled" if moved else "booked",
        conversation=conversation,
        appointment=appointment,
        priority="high",
        title=(f"Sales call moved: {who}, {when}" if moved else f"Sales call: {who}, {when}"),
        text="\n".join(lines),
        dedupe_key=f"{'rescheduled' if moved else 'booked'}:{appointment.pk}:{stamp}",
        crm_url=crm_url,
    )
    return True


# The reminder and its taps ----------------------------------------------------------------------------------------

REMINDER = {
    "en": "Hi {name}, a reminder of your {minutes}-minute call with our sales team today at {time}. We'll call you on this number.",
    "ar": "مرحباً {name}، نذكّرك بمكالمتك مع فريق المبيعات لدينا اليوم الساعة {time}، ومدتها {minutes} دقائق. سنتصل بك على هذا الرقم.",
    "ur_latin": "Hi {name}, yaad dihani: aaj {time} par hamari sales team ke saath aap ki {minutes} minute ki call hai. Hum aap ko isi number par call karenge.",
    "ur": "السلام علیکم {name}، یاد دہانی: آج {time} پر ہماری سیلز ٹیم کے ساتھ آپ کی {minutes} منٹ کی کال ہے۔ ہم آپ کو اسی نمبر پر کال کریں گے۔",
    "hi_latin": "Hi {name}, reminder: aaj {time} par hamari sales team ke saath aapki {minutes} minute ki call hai. Hum aapko isi number par call karenge.",
    "hi": "नमस्ते {name}, याद दिला दें: आज {time} पर हमारी सेल्स टीम के साथ आपकी {minutes} मिनट की कॉल है। हम आपको इसी नंबर पर कॉल करेंगे।",
}
# "On My Way" on a call's reminder: they are ready for the call (spec §3.3.7).
READY = {
    "en": "Perfect, our sales team will call you shortly on this number.",
    "ar": "ممتاز، سيتصل بك فريق المبيعات لدينا قريباً على هذا الرقم.",
    "ur_latin": "Perfect, hamari sales team thodi der mein aap ko isi number par call karegi.",
    "ur": "بہت خوب، ہماری سیلز ٹیم تھوڑی دیر میں آپ کو اسی نمبر پر کال کرے گی۔",
    "hi_latin": "Perfect, hamari sales team thodi der mein aapko isi number par call karegi.",
    "hi": "बहुत बढ़िया, हमारी सेल्स टीम थोड़ी देर में आपको इसी नंबर पर कॉल करेगी।",
}
# "Running Late" on a call's reminder: there is no arrival to wait for, only a later time for the call.
LATER = {
    "en": "No problem. What time should our sales team call you instead?",
    "ar": "لا مشكلة. في أي وقت تفضّل أن يتصل بك فريق المبيعات بدلاً من ذلك؟",
    "ur_latin": "Koi baat nahi. Hamari sales team aap ko kis waqt call kare?",
    "ur": "کوئی بات نہیں۔ ہماری سیلز ٹیم آپ کو کس وقت کال کرے؟",
    "hi_latin": "Koi baat nahi. Hamari sales team aapko kis time call kare?",
    "hi": "कोई बात नहीं। हमारी सेल्स टीम आपको किस समय कॉल करे?",
}


def reminder_text(appointment, first_name: str, language: str = "en") -> str:
    """The free-form reminder of a sales call, in the customer's language (spec §3.3.7)."""
    lang = _lang(language)
    head = REMINDER[lang]
    if not first_name:
        head = head.replace(" {name}", " there" if lang == "en" else "").replace("{name}", "")
    return " ".join(head.format(name=first_name, time=hours.time_label(appointment.starts_at), minutes=MINUTES).split())


def template_place(appointment, default: str) -> str:
    """The approved meeting reminder's {{3}}: "this number (our team will call you)" for a call, else ``default``."""
    return TEMPLATE_PLACE if is_sales_call(appointment) else default


def tap_line(action: str, language: str) -> str:
    """Code's answer to a tap on a call's reminder, '' when the visit's own goes (a reschedule: two free call slots)."""
    lang = _lang(language)
    if action == "on_my_way":
        return READY[lang]
    if action == "running_late":
        return LATER[lang]
    return ""


def tap_alert(action: str, name: str, at: str, phone: str) -> tuple[str, str] | None:
    """(title, text) of the alert for a tap on a call's reminder; None for a reschedule (the visit's own words fit)."""
    if action == "on_my_way":
        return f"{name} is ready for the call", f"{name} tapped On My Way for the {at} sales call: they are ready for it ({phone})."
    if action == "running_late":
        return f"{name} wants a later call", f"{name} tapped Running Late for the {at} sales call. We asked what time suits them ({phone})."
    return None
