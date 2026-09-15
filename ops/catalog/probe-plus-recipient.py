"""Probe whether +971… stops Alots India-prefix mangling for 971559298388.

Sends a real template once; prints contacts wa_id only.
"""

from apps.catalog.models import WaTemplate
from apps.gateway.client import AlotsClient
from apps.inbox.models import Conversation
from apps.inbox.services import build_template_components, format_recipient_for_gateway

conv = Conversation.objects.get(pk=637)
tpl = WaTemplate.objects.get(pk=1303)
to_bare = conv.contact.wa_id
to_plus = format_recipient_for_gateway(to_bare)
components = build_template_components(
    tpl, {"1": "probe", "2": "A7", "3": "Villa", "4": "1"}
)
print(f"sending to_bare={to_bare!r} to_plus={to_plus!r} tpl={tpl.name}", flush=True)
res = AlotsClient().send_template(
    conv.number.phone_number_id,
    to_plus,
    tpl.name,
    tpl.language,
    components,
)
contacts = (res or {}).get("contacts") or []
wa = contacts[0].get("wa_id") if contacts else None
inp = contacts[0].get("input") if contacts else None
print(f"response_wa_id={wa!r} input={inp!r}", flush=True)
print(
    f"ok={wa == to_bare} mangled={wa == '91' + to_bare}",
    flush=True,
)
