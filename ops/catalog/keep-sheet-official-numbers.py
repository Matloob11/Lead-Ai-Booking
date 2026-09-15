"""Official roster = Dubai Waba Number details sheet (gid 2080113227).

Deactivate catalog rows not on the sheet. Never delete (conversations PROTECT).
Insert the four sheet numbers that Official is missing.
"""

from apps.catalog.models import WabaNumber
from apps.inbox.models import Conversation

KEEP = {
    "447360267436",
    "447360545726",
    "447361590663",
    "447366360875",
    "447401457395",
    "447414115945",
    "447414121510",
    "447414128143",
    "447414131370",
    "447426758743",
    "447426912372",
    "447426961172",
    "447427924701",
    "447428322124",
    "447447178015",
    "447447179547",
    "447447184236",
    "447447187245",
    "447455749638",
    "447462178442",
    "447462536357",
    "447462539765",
    "447463947958",
    "447476928266",
    "447476957698",
    "447476959465",
    "447476987129",
    "447476992120",
    "447476993013",
    "447476993627",
    "447476994353",
    "447476994508",
    "447476994670",
    "447476994839",
    "447576534429",
    "447723011791",
    "447723185014",
    "447723185187",
    "447723186020",
    "447723321328",
    "447723325193",
    "447723351149",
    "447723356623",
    "447723374770",
    "447723430080",
    "447723448895",
    "447723458662",
    "447723461484",
    "447723474991",
    "447723495849",
    "447723504881",
    "447723545003",
    "447723576678",
    "447723608460",
    "447727624256",
    "447735852054",
    "447782361546",
    "447782639429",
    "447828569383",
    "447830355926",
    "447846855263",
    "447846870802",
    "447846888462",
    "447882968294",
    "971507563104",
    "971524077268",
    "971524473103",
    "971524492026",
    "971527514497",
    "971529312577",
    "971543752608",
    "971555306149",
    "971555497521",
    "971555689029",
    "971555716422",
    "971555817694",
    "971555832603",
    "971555850765",
    "971555956439",
    "971556037342",
    "971556059331",
    "971556082710",
    "971556354628",
    "971556441831",
    "971556748730",
    "971556829046",
    "971557327268",
    "971557466914",
    "971558448678",
    "971559193588",
    "971559430556",
    "971559477395",
    "971559481572",
    "971559632895",
    "971559668904",
    "971559759052",
    "971559783176",
    "971559791401",
    "971564821835",
}

ADD = (
    ("447361590663", "866328923229012", "1375784833898414", "Green Haven Properties"),
    ("447414131370", "879961421870961", "749382257506214", "Luxe Towers Realty"),
    ("447414128143", "941286345724859", "862690896160557", "Grand Park Real Estate"),
    ("447723351149", "1159800127227627", "1020414067303464", "Tranquil Crest Villas"),
)

assert len(KEEP) == 99
assert {p for p, _, _, _ in ADD} <= KEEP

print("active_before", WabaNumber.objects.filter(is_active=True).count(), flush=True)

extras = list(
    WabaNumber.objects.exclude(phone_number__in=KEEP).values_list("phone_number", "is_active")
)
print("extras", len(extras), flush=True)
for phone, active in extras:
    chats = Conversation.objects.filter(number__phone_number=phone).count()
    print(f"extra {phone} active={active} chats={chats}", flush=True)

deactivated = (
    WabaNumber.objects.filter(is_active=True)
    .exclude(phone_number__in=KEEP)
    .update(is_active=False)
)
print("deactivated_now", deactivated, flush=True)

created = 0
skipped = 0
for phone, pnid, waba, name in ADD:
    clash = WabaNumber.objects.filter(phone_number=phone).first() or WabaNumber.objects.filter(
        phone_number_id=pnid
    ).first()
    if clash is not None:
        if not clash.is_active:
            clash.is_active = True
            clash.save(update_fields=["is_active"])
            print("reactivated", phone, flush=True)
        else:
            print("skip", phone, flush=True)
        skipped += 1
        continue
    WabaNumber.objects.create(
        phone_number=phone,
        phone_number_id=pnid,
        waba_business_id=waba,
        display_name=name,
        label=name,
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        webhook_configured=False,
    )
    created += 1
    print("created", phone, name, flush=True)

active = list(
    WabaNumber.objects.filter(is_active=True).values_list("phone_number", flat=True)
)
active_set = set(active)
print("created_count", created, flush=True)
print("skipped_count", skipped, flush=True)
print("active_after", len(active_set), flush=True)
print("active_971", sum(1 for p in active_set if p.startswith("971")), flush=True)
print("active_44", sum(1 for p in active_set if p.startswith("44")), flush=True)
missing = sorted(KEEP - active_set)
extra_active = sorted(active_set - KEEP)
print("missing_from_sheet", len(missing), *missing, flush=True)
print("extra_still_active", len(extra_active), *extra_active, flush=True)
print(
    "dubai01_hidden_chats",
    Conversation.objects.filter(number__phone_number="971563523109").count(),
    flush=True,
)
