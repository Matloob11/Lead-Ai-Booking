# Clear WBBOX company names from the 16 manual Official numbers so the
# inbox filter shows the assigned agent (or "Not assigned"), not the brand.

from apps.catalog.models import WabaNumber

qs = WabaNumber.objects.filter(source=WabaNumber.Source.MANUAL)
updated = qs.update(label="", display_name="")
print("cleared", updated)
for row in qs.order_by("phone_number"):
    print(row.phone_number, "label=", repr(row.label), "display=", repr(row.display_name), "title=", row.title)
