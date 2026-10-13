# Run through `ops/wa.sh probe-lead-ai-flow`: checks the Lead AI routing rules
# on the LIVE code and database inside ONE transaction that is ALWAYS rolled
# back. Nothing is sent and nothing stays:
#   - run_campaign is replaced, so no campaign task is queued and no template
#     goes out (process_recipient, the only sender, is never called);
#   - the channel layer is replaced, so no live event reaches any browser;
#   - no Message row is made, so no Sara / AI desk / CRM mirror signal runs;
#   - the customers 999000000002 and 999000000003 and every campaign, chat and
#     recipient made here vanish with the rollback (checked at the end).
import json
from unittest import mock

from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Agent
from apps.campaigns import crm_leads
from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import NumberAssignment, WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation
from apps.inbox.serializers import serialize_conversation
from apps.leadai import lane
from apps.leadai.models import LeadAiCampaign, LeadAiChat

HOST = "wa.srv1802669.hstgr.cloud"
NEW, OLD = "999000000002", "999000000003"
results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


class Rollback(Exception):
    pass


class FakeLayer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append(message.get("event"))


def api(user):
    client = APIClient(HTTP_HOST=HOST)
    client.force_authenticate(user=user)
    return client


def body(response):
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {}


campaigns_before = Campaign.objects.count()
layer = FakeLayer()
try:
    with transaction.atomic(), mock.patch.object(crm_leads, "run_campaign") as run_campaign, mock.patch(
        "apps.inbox.events.get_channel_layer", return_value=layer
    ):
        admin = Agent.objects.get(bitrix_user_id="2311", is_active=True)
        number_a = WabaNumber.objects.get(phone_number="971524077268")
        number_b = WabaNumber.objects.filter(is_active=True).exclude(pk=number_a.pk).order_by("pk").first()
        template = next(
            t
            for t in WaTemplate.objects.filter(
                waba_business_id=number_a.waba_business_id, status=WaTemplate.Status.APPROVED
            ).order_by("pk")
            if t.variable_count == 0 and not t.requires_header_media and "{{" not in json.dumps(t.components)
        )
        print("using template", template.pk, template.name, "| number A", number_a.phone_number, "| number B", number_b.phone_number)

        # The OLD customer already talks to us on number A (with history) and on number B.
        old_contact = Contact.objects.create(wa_id=OLD, display_name="ZZ probe old (rolled back)")
        now = timezone.now()
        conv_old_a = Conversation.objects.create(
            number=number_a, contact=old_contact, assigned_agent=admin, last_message_at=now, last_message_preview="earlier chat"
        )
        conv_old_b = Conversation.objects.create(
            number=number_b, contact=old_contact, assigned_agent=admin, last_message_at=now, last_message_preview="other number"
        )

        # 1. The popup's send with the box ticked, as the PHP tool forwards it.
        leads = [
            {"id": 900000001, "name": "ZZ probe new (rolled back)", "phone": "+" + NEW},
            {"id": 900000002, "name": "ZZ probe old (rolled back)", "phone": OLD},
        ]
        out = crm_leads.send_from_leads(
            agent=admin, template_id=template.pk, leads=leads, number_id=number_a.pk, entity="lead", lead_ai=True
        )
        campaign = Campaign.objects.get(pk=out["campaign_id"])
        check("send answers lead_ai true", out.get("lead_ai") is True, out.get("lead_ai"))
        check("campaign name says Lead AI", "Lead AI · " in campaign.name, campaign.name)
        check("campaign marked Lead AI", LeadAiCampaign.objects.filter(campaign=campaign).exists())
        check("task queued once, after the mark", run_campaign.delay.call_args_list == [mock.call(campaign.pk)], run_campaign.delay.call_args_list)

        # 2. What process_recipient does just before each send (the send itself is not made).
        recipients = {r.phone: r for r in campaign.recipients.all()}
        check("two recipients", set(recipients) == {NEW, OLD}, sorted(recipients))
        for recipient in recipients.values():
            lane.before_campaign_send(campaign, recipient)
        conv_new = Conversation.objects.get(number=number_a, contact__wa_id=NEW)
        chat_new = LeadAiChat.objects.get(conversation=conv_new)
        check(
            "new customer: chat made straight into Lead AI",
            chat_new.active and chat_new.campaign_id == campaign.pk and chat_new.crm_entity == "lead" and chat_new.crm_id == 900000001,
            (chat_new.active, chat_new.campaign_id, chat_new.crm_entity, chat_new.crm_id),
        )
        check("new customer: owned by the sender", conv_new.assigned_agent_id == admin.pk, conv_new.assigned_agent_id)
        check(
            "same customer + same number: the SAME chat moved, history kept",
            LeadAiChat.objects.filter(conversation=conv_old_a, active=True).exists()
            and Conversation.objects.filter(number=number_a, contact__wa_id=OLD).count() == 1,
        )
        check(
            "same customer + other number: stays in the main inbox",
            not LeadAiChat.objects.filter(conversation=conv_old_b).exists(),
        )

        # 3. What the panel sees, as the admin.
        a = api(admin)
        r = a.get("/api/inbox/conversations/", {"q": NEW, "limit": 10}, secure=True)
        check("main inbox list hides the new Lead AI chat", r.status_code == 200 and body(r).get("count") == 0, (r.status_code, body(r).get("count")))
        r = a.get("/api/inbox/conversations/", {"q": OLD, "limit": 10}, secure=True)
        ids = [row["id"] for row in body(r).get("results", [])]
        check("main inbox list keeps only the other-number chat", ids == [conv_old_b.pk], ids)
        r = a.get("/api/leadai/chats/", {"q": "99900000000", "limit": 10}, secure=True)
        rows = body(r).get("results", [])
        check("Lead AI list holds both moved chats", sorted(x["id"] for x in rows) == sorted([conv_new.pk, conv_old_a.pk]), [x["id"] for x in rows])
        info = next((x.get("lead_ai_info") or {} for x in rows if x["id"] == conv_new.pk), {})
        check("Lead AI row names its campaign and CRM record", info.get("campaign_name") == campaign.name and info.get("crm_entity") == "lead", info)
        r = a.get(f"/api/inbox/conversations/{conv_new.pk}/messages/", {"limit": 1}, secure=True)
        check("a link into the chat says lead_ai, so the inbox hands it over", body(r).get("conversation", {}).get("lead_ai") is True, r.status_code)
        fresh_a = Conversation.objects.get(pk=conv_old_a.pk)
        fresh_b = Conversation.objects.get(pk=conv_old_b.pk)
        check("serializer flag", serialize_conversation(fresh_a)["lead_ai"] is True and serialize_conversation(fresh_b)["lead_ai"] is False)
        check(
            "live events renamed only for Lead AI chats",
            lane.event_name(fresh_a, "message.new") == "leadai.message.new" and lane.event_name(fresh_b, "message.new") == "message.new",
        )

        # 4. The gate: an agent who does not own the chat can neither open nor move it.
        assignment = (
            NumberAssignment.objects.filter(
                number=number_a, is_active=True, agent__is_active=True, agent__is_wa_admin=False, agent__is_superuser=False
            )
            .select_related("agent")
            .first()
        )
        other = assignment.agent if assignment else Agent.objects.filter(is_active=True, is_wa_admin=False, is_superuser=False).first()
        print("other agent", other.pk, "holds number A:", bool(assignment))
        o = api(other)
        r = o.get(f"/api/leadai/chats/{conv_new.pk}/", secure=True)
        check("gate: someone else's Lead AI chat will not open", r.status_code == 404, r.status_code)
        r = o.post(f"/api/leadai/chats/{conv_new.pk}/move-to-inbox/", secure=True)
        check("gate: and cannot be moved", r.status_code == 404, r.status_code)
        r = o.get("/api/leadai/chats/", {"q": "99900000000"}, secure=True)
        check("gate: nor listed", body(r).get("count") == 0, body(r).get("count"))
        r = o.get(f"/api/inbox/conversations/{conv_new.pk}/messages/", {"limit": 1}, secure=True)
        check("gate: nor read through the inbox route", r.status_code in (403, 404), r.status_code)

        # The agent who owns it (the one who sent the campaign) opens and moves it.
        Conversation.objects.filter(pk=conv_new.pk).update(assigned_agent=other)
        r = o.get(f"/api/leadai/chats/{conv_new.pk}/", secure=True)
        check("owner opens their Lead AI chat", r.status_code == 200, r.status_code)
        layer.sent.clear()
        r = o.post(f"/api/leadai/chats/{conv_new.pk}/move-to-inbox/", secure=True)
        chat_new.refresh_from_db()
        check("Move to inbox: 200", r.status_code == 200, (r.status_code, body(r)))
        check("Move to inbox: row off, mover recorded", (not chat_new.active) and chat_new.moved_by_id == other.pk and chat_new.moved_at is not None)
        check(
            "Move to inbox: announced as a plain conversation.updated",
            "conversation.updated" in layer.sent and not any(str(e).startswith("leadai.") for e in layer.sent),
            layer.sent,
        )
        r = o.post(f"/api/leadai/chats/{conv_new.pk}/move-to-inbox/", secure=True)
        check("Move again: 409", r.status_code == 409, r.status_code)
        r = a.get("/api/inbox/conversations/", {"q": NEW, "limit": 10}, secure=True)
        check("moved chat is back in the main inbox", body(r).get("count") == 1, body(r).get("count"))
        r = a.get("/api/leadai/chats/", {"q": NEW}, secure=True)
        check("moved chat left Lead AI", body(r).get("count") == 0, body(r).get("count"))

        # 5. A retry of the SAME campaign keeps the agent's move; a NEW Lead AI campaign brings it back.
        lane.before_campaign_send(campaign, recipients[NEW])
        check("same-campaign retry keeps it in the inbox", not LeadAiChat.objects.get(conversation=conv_new).active)
        out2 = crm_leads.send_from_leads(
            agent=admin, template_id=template.pk, leads=leads[:1], number_id=number_a.pk, entity="lead", lead_ai=True
        )
        campaign2 = Campaign.objects.get(pk=out2["campaign_id"])
        lane.before_campaign_send(campaign2, campaign2.recipients.get())
        check("a new Lead AI campaign brings it back", LeadAiChat.objects.get(conversation=conv_new).active)

        # 6. A normal campaign moves nothing either way.
        out3 = crm_leads.send_from_leads(
            agent=admin, template_id=template.pk, leads=leads, number_id=number_a.pk, entity="lead", lead_ai=False
        )
        campaign3 = Campaign.objects.get(pk=out3["campaign_id"])
        check(
            "normal campaign: not marked, plain name",
            out3.get("lead_ai") is False
            and not LeadAiCampaign.objects.filter(campaign=campaign3).exists()
            and "Lead AI" not in campaign3.name,
            campaign3.name,
        )
        for recipient in campaign3.recipients.all():
            lane.before_campaign_send(campaign3, recipient)
        check("normal campaign leaves a Lead AI chat in Lead AI", LeadAiChat.objects.filter(conversation=conv_old_a, active=True).exists())
        check("normal campaign does not pull a main-inbox chat in", not LeadAiChat.objects.filter(conversation=conv_old_b).exists())

        # 7. "Resend skipped" of a Lead AI campaign is a Lead AI campaign too.
        out4 = crm_leads.send_from_leads(
            agent=admin, template_id=template.pk, leads=leads[:1], number_id=number_a.pk, entity="lead", lead_ai=False
        )
        campaign4 = Campaign.objects.get(pk=out4["campaign_id"])
        lane.inherit_campaign(campaign, campaign4)
        check("resend of a Lead AI campaign inherits the mark", LeadAiCampaign.objects.filter(campaign=campaign4).exists())

        # 8. The gateway accepted the send: the chat is confirmed.
        sent = recipients[OLD]
        sent.status = CampaignRecipient.Status.SENT
        sent.conversation = conv_old_a
        sent.save(update_fields=["status", "conversation"])
        check("an accepted send confirms the chat", LeadAiChat.objects.get(conversation=conv_old_a).confirmed)
        check("no task left the probe", run_campaign.delay.call_count == 4, run_campaign.delay.call_count)
        raise Rollback
except Rollback:
    pass

left = {
    "contacts": Contact.objects.filter(wa_id__in=[NEW, OLD]).count(),
    "lead_ai_chats": LeadAiChat.objects.filter(conversation__contact__wa_id__in=[NEW, OLD]).count(),
    "campaigns_added": Campaign.objects.count() - campaigns_before,
}
check("rolled back: nothing of the probe stayed", left == {"contacts": 0, "lead_ai_chats": 0, "campaigns_added": 0}, left)

for ok, name, detail in results:
    print("PASS" if ok else "FAIL", "|", name, "" if ok else f"| {detail}")
print("passed", sum(1 for ok, _, _ in results if ok), "of", len(results))
print("PROBE_OK")
