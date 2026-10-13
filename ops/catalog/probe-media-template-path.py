# Read-only, run through `ops/wa.sh probe-media-template-path`:
# which way can the live stack mint the sample "h" handle that Meta needs
# for an IMAGE/VIDEO-header template? Prints yes/no and session state only.
from django.conf import settings
from apps.gateway.models import PanelSession


def flag(name):
    return "yes" if (getattr(settings, name, "") or "").strip() else "no"


print("META_GRAPH_ACCESS_TOKEN set:", flag("META_GRAPH_ACCESS_TOKEN"))
print("META_APP_ID set:", flag("META_APP_ID"))
print("META_GRAPH_BASE_URL:", getattr(settings, "META_GRAPH_BASE_URL", "") or "(default)")
print("ALOTS_UI_COOKIE_B64 set:", flag("ALOTS_UI_COOKIE_B64"))
ps = PanelSession.objects.order_by("-id").first()
if ps is None:
    print("PanelSession: none")
else:
    print("PanelSession expires_at:", ps.expires_at)
    print("PanelSession last_ok_at:", ps.last_ok_at)
    print("PanelSession last_error:", (ps.last_error or "")[:160])
    print("PanelSession updated_at:", ps.updated_at)
print("PROBE_OK")
