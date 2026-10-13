# Run through `ops/wa.sh probe-lead-ai-cleanup`: deletes the synthetic chat
# probe-lead-ai-fixture made (customer wa_id 999000000001 only), with its
# messages and its Lead AI row. Touches nothing else. Idempotent.
from apps.inbox.models import Contact, Conversation

WA_ID = "999000000001"

contact = Contact.objects.filter(wa_id=WA_ID).first()
if contact is None:
    print("nothing to clean")
else:
    ids = list(Conversation.objects.filter(contact=contact).values_list("pk", flat=True))
    deleted = Conversation.objects.filter(contact=contact).delete()
    contact.delete()
    print("deleted conversations", ids, deleted)
print("PROBE_OK")
