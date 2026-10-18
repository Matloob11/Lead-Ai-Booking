"""inbox.visibility with both of its 2026-10-17 rules at once: Cursor's staff_only (a Rotate-campaign thread is hidden
from the number's agent, claimed or not) over Claude's Lead AI desk clause (an agent with Lead AI access opens every
active Lead AI chat on any number, Q37). The staff_only exclusion covers the desk too; a panel admin still sees all."""

from apps.catalog.models import NumberAssignment
from apps.inbox.models import Contact, Conversation
from apps.inbox.visibility import visible_conversation_q
from apps.leadai.models import LeadAiChat
from apps.leadai.tests.test_desk import DeskBase


class StaffOnlyOverTheDeskTests(DeskBase):
    def setUp(self):
        super().setUp()
        NumberAssignment.objects.create(number=self.number, agent=self.plain)
        self.normal = self.thread()
        self.rotate = self.thread(staff_only=True)
        self.rotate_claimed = self.thread(staff_only=True, assigned_agent=self.plain)
        self.lead_ai = self.chat()  # an active Lead AI chat on self.number, owned by the campaign sender
        self.rotate_lead_ai = self.chat()
        Conversation.objects.filter(pk=self.rotate_lead_ai.pk).update(staff_only=True)

    def thread(self, **fields):
        contact = Contact.objects.create(wa_id=next(self.phones))
        return Conversation.objects.create(number=self.number, contact=contact, **fields)

    def visible(self, user):
        return set(Conversation.objects.filter(visible_conversation_q(user)).values_list("pk", flat=True))

    def test_the_numbers_agent_never_sees_a_rotate_thread(self):
        seen = self.visible(self.plain)
        self.assertIn(self.normal.pk, seen)
        self.assertNotIn(self.rotate.pk, seen)
        self.assertNotIn(self.rotate_claimed.pk, seen)  # claimed by them, still hidden

    def test_a_desk_agent_sees_lead_ai_chats_but_no_rotate_thread(self):
        seen = self.visible(self.desker)
        self.assertIn(self.lead_ai.pk, seen)
        self.assertNotIn(self.rotate_lead_ai.pk, seen)
        self.assertNotIn(self.rotate.pk, seen)
        self.assertNotIn(self.normal.pk, seen)  # not a Lead AI chat, and no number of theirs

    def test_an_agent_without_lead_ai_access_gets_no_desk(self):
        self.assertNotIn(self.lead_ai.pk, self.visible(self.plain))

    def test_a_panel_admin_still_sees_everything(self):
        seen = self.visible(self.admin)
        for conversation in (self.normal, self.rotate, self.rotate_claimed, self.lead_ai, self.rotate_lead_ai):
            self.assertIn(conversation.pk, seen)

    def test_a_closed_lead_ai_chat_leaves_the_desk(self):
        LeadAiChat.objects.filter(conversation=self.lead_ai).update(active=False)
        self.assertNotIn(self.lead_ai.pk, self.visible(self.desker))
