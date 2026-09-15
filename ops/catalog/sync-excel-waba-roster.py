# Official API roster:
# - A7GroupWBX / source=sync: never touched
# - Dubai01 unmatched: deactivate (hide from panel)
# - Excel-matched numbers + all Dubai11: insert as manual, empty label

from apps.catalog.models import WabaNumber

KEEP_DUBAI01 = {"447476959465"}  # CleanSlate — Excel match
DEACTIVATE_DUBAI01 = {
    "971563523109",
    "447414120776",
    "447882967787",
    "447882963471",
    "447479325117",
    "447846864137",
    "447480785539",
    "447480775697",
    "447476951819",
    "447476963121",
    "447727759813",
    "447476545324",
    "447456440254",
    "447360541180",
    "447481338761",
}

# (phone, phone_number_id, waba_business_id) — no brand labels
ADD = [
    # Dubai02 Excel matches
    ("447401457395", "810596165478108", "1645173380201130"),
    ("447366360875", "904829816038500", "2303247923450706"),
    ("447476928266", "812172828654558", "1161543808762210"),
    ("447360545726", "772858839254379", "2560235551042777"),
    ("447476987129", "845282148676647", "844386631448915"),
    ("447428322124", "772479489292535", "2032895730796656"),
    # Dubai03 Excel matches
    ("447830355926", "897151540139875", "810807371568946"),
    ("447782639429", "886995197830768", "1482060389727896"),
    ("447447187245", "821677951037431", "1248670820631413"),
    ("447447178015", "823005090901967", "705344782095768"),
    ("447427924701", "838634556002406", "854057616961197"),
    ("447426758743", "809151668956711", "4349717028595823"),
    ("447426961172", "866976563166742", "1885280485430265"),
    ("447447184236", "874770505720022", "1331491795025361"),
    ("447426912372", "777176038823595", "888564143505142"),
    # Dubai04 Excel matches
    ("447462363289", "827764293760228", "1011973244419870"),
    ("447882968294", "862215323642235", "1163058018586596"),
    ("447846870802", "860815920446137", "2101463477259773"),
    ("447846855263", "811774572027277", "1871060046818798"),
    ("447735852054", "867063513155749", "1451343515968618"),
    ("447727624256", "842518615614171", "750689094651737"),
    ("447723430080", "845214378676674", "704027162752261"),
    ("447475922171", "891380590717601", "2681306488869104"),
    ("447455749638", "910803195439776", "1331769318690750"),
    ("447462539765", "891682544021115", "1595385731845344"),
    ("447447179547", "903318269523195", "1486511162644106"),
    ("447846888462", "891503310706719", "2041129286645347"),
    # Dubai05 Excel matches
    ("447476993013", "840511242486761", "1321138569763713"),
    ("447476993627", "872569462611937", "1584790222654583"),
    ("447476994508", "827597903779932", "1221284173175206"),
    ("447476994353", "823334377540224", "3102636229908142"),
    ("447476994670", "846982331839630", "2246155415796427"),
    ("447476994839", "904904739376735", "2675672512787790"),
    ("447782361546", "962759943577491", "1189223359820749"),
    ("447828569383", "944092118778726", "3509177285888965"),
    # Dubai06 Excel matches
    ("447476959385", "849326698271914", "1475550733527111"),
    ("447476992120", "874009125801831", "4203800606616537"),
    # Dubai07 Excel matches
    ("447414121510", "954177434436146", "1731415400872414"),
    ("447414115945", "829445176928142", "672727612586996"),
    # Dubai10 Excel match
    ("971559759052", "1011707068692657", "1429925001914116"),
    # Dubai11 all
    ("447462178442", "1170024862868724", "963708416684811"),
    ("447463947958", "1234986146363726", "4501666486771681"),
    ("447576534429", "1251711094687569", "1547823566695166"),
    ("447476957698", "1185093164691569", "2646781339049968"),
    ("447462536357", "1155327167674930", "1020722297394415"),
    ("447360267436", "1268836452972273", "1332030291914336"),
    ("447723495849", "1223935820806741", "28611118331810926"),
    ("447723461484", "1303537242843664", "875599158505060"),
    ("447723576678", "1181923661679406", "1053332550487980"),
    ("447723186020", "1157175417485999", "1589977955880219"),
    ("447723185187", "1128687953672086", "1030084423290304"),
    ("447723504881", "1230093696851872", "1021067944218959"),
    ("447723325193", "1280150751837616", "1548358103650886"),
    ("447723458662", "1248145758380521", "2879071629104339"),
]

phones = [p for p, _, _ in ADD]
ids = [i for _, i, _ in ADD]
assert len(phones) == len(set(phones)), "duplicate phones in ADD"
assert len(ids) == len(set(ids)), "duplicate phone_number_ids in ADD"
assert KEEP_DUBAI01.isdisjoint(DEACTIVATE_DUBAI01)
assert KEEP_DUBAI01.isdisjoint(set(phones))
assert DEACTIVATE_DUBAI01.isdisjoint(set(phones))

sync_before = WabaNumber.objects.filter(source=WabaNumber.Source.SYNC, is_active=True).count()
print("sync_active_before", sync_before)

deactivated = (
    WabaNumber.objects.filter(
        source=WabaNumber.Source.MANUAL,
        phone_number__in=DEACTIVATE_DUBAI01,
        is_active=True,
    ).update(is_active=False)
)
print("deactivated_dubai01", deactivated)
kept = WabaNumber.objects.filter(phone_number__in=KEEP_DUBAI01, is_active=True).count()
print("kept_cleanSlate", kept)

created = 0
skipped = 0
for phone, pnid, waba in ADD:
    clash = WabaNumber.objects.filter(phone_number_id=pnid).first() or WabaNumber.objects.filter(
        phone_number=phone
    ).first()
    if clash is not None:
        if clash.source == WabaNumber.Source.SYNC:
            print("BLOCK sync", phone)
            skipped += 1
            continue
        print("skip", phone)
        skipped += 1
        continue
    WabaNumber.objects.create(
        phone_number=phone,
        phone_number_id=pnid,
        waba_business_id=waba,
        display_name="",
        label="",
        community="",
        quality_rating=WabaNumber.Quality.UNKNOWN,
        verification_status="",
        messaging_limit="",
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        webhook_configured=False,
        synced_at=None,
    )
    print("created", phone)
    created += 1

sync_after = WabaNumber.objects.filter(source=WabaNumber.Source.SYNC, is_active=True).count()
print("created_count", created)
print("skipped_count", skipped)
print("expected_new", len(ADD))
print("sync_active_after", sync_after)
print("manual_active", WabaNumber.objects.filter(source=WabaNumber.Source.MANUAL, is_active=True).count())
print("active_total", WabaNumber.objects.filter(is_active=True).count())
if sync_after != sync_before:
    print("ERROR sync count changed")
