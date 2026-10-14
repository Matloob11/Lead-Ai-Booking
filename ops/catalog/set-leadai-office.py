"""Set the Lead AI office's Google Maps link and pin, as the AI settings dialog would.

Run through `ops/wa.sh set-leadai-office URL LAT LNG`: the verb passes the three
values as environment variables and pipes this file into `manage.py shell` in the
web container. The values are checked with the settings view's own validators
(apps.leadai.views), and the change is recorded in the settings history.
"""

import os
from decimal import Decimal

from django.utils import timezone

from apps.leadai import views
from apps.leadai.models import LeadAiSettings

url = os.environ.get("LEADAI_OFFICE_MAPS_URL", "").strip()
lat_text = os.environ.get("LEADAI_OFFICE_LAT", "").strip()
lng_text = os.environ.get("LEADAI_OFFICE_LNG", "").strip()

problems = []
url_error = views._maps_url_error(url) if url else "No Maps link given."
if url_error:
    problems.append(url_error)
lat, lat_error = views._coordinate(lat_text, Decimal(-90), Decimal(90))
lng, lng_error = views._coordinate(lng_text, Decimal(-180), Decimal(180))
if lat_error or lat is None:
    problems.append(f"Latitude {lat_error or 'is missing'}.")
if lng_error or lng is None:
    problems.append(f"Longitude {lng_error or 'is missing'}.")

if problems:
    print("REFUSED:", " ".join(problems))
else:
    row = LeadAiSettings.load()
    changes = {}
    for field, new in (("office_maps_url", url), ("office_latitude", lat), ("office_longitude", lng)):
        old = getattr(row, field)
        if old != new:
            changes[field] = [str(old), str(new)]
            setattr(row, field, new)
    if changes:
        row.history = (list(row.history or []) + [
            {"at": timezone.now().isoformat(), "by": "ops/wa.sh", "changes": changes}
        ])[-100:]
        row.save()
    print("office_maps_url=", row.office_maps_url)
    print("office_latitude=", row.office_latitude, "office_longitude=", row.office_longitude, "has_pin=", row.has_pin)
    print("changed:", ", ".join(changes) or "nothing (already set)")
