"""Batch 2d, package "CRM writes" (launch review issues 1, 15, 19's Django side, 25 and 26; side_effects.json).

- A. a shops "no" (assistant/lost.py): Bot Status Lost always; the move to Not Interested or Junk only for a lead
  nobody worked for seven days and with no open to-do, read through the REST client just before (a failed read
  moves nothing, and nobody's to-do is closed or changed); the timeline comment and the alert to the lead's owner
  and the Lead AI alert list;
- B. the lead's fields: a value it holds already is never posted (no change-log line); a business activity is a
  business, never a home they want or a sentence;
- C. a Bot Status a person set in Bitrix outranks ours (bitrix_status.remember);
- D. notes keep only the customer's own questions, and a budget of ours is no budget of theirs (crm_facts.py);
- E. names: no job title greeted, the case put right, never "Customer: -"; "No thankyou" is a no;
- F. a voice note's words on the lead's timeline (the mirror writes "[audio]");
- G. a shop photo sent with no caption keeps its Lead AI payload (issue 25);
- H. the new eval scenarios fail without their guards.

Bitrix's answers are the launch leads' own, as side_effects.json records them (79641 chat 42, 79417 chat 120, 79428
chat 116, 79420 chat 118, 79419 chat 119, 79321 chat 134, 78833 chat 91, 79341 chat 132), on this suite's clock:
Monday 12 October 2026, 14:00 Dubai, for the launch's Thursday.
"""

import datetime as dt
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import override_settings

from apps.catalog.models import WabaNumber
from apps.crmlink import client
from apps.crmlink import tasks as crmlink_tasks
from apps.gateway import ingest
from apps.inbox.models import Conversation, MediaAsset, Message
from apps.leadai import bitrix_status, tasks
from apps.leadai.assistant import crm, crm_facts, crm_fields, engine, filters, lost, nudges, people, rules, schema, transcribe
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChatState, LeadAiCrmField, LeadAiSettings, LeadAiTranscript, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, _outbound
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_shops_playbook import ShopsBase, shop_answer

DAY = dt.timedelta(days=1)
MOVE = crm_fields.LOST
STATUS = crm_fields.FIELD_BOT_STATUS


def iso(moment: dt.datetime) -> str:
    return moment.isoformat()


# The launch leads as crm.lead.get answers them, on this clock. An idle lead first: months old, only our own tool
# (user 1) has changed it lately, its stage is open.
IDLE_LEAD = {
    "ID": "555", "STATUS_ID": "IN_PROCESS", "STATUS_SEMANTIC_ID": "P", "ASSIGNED_BY_ID": "2298",
    "DATE_CREATE": "2026-06-01T10:00:00+04:00", "DATE_MODIFY": iso(NOW - dt.timedelta(minutes=30)), "MODIFY_BY_ID": "1",
    "MOVED_BY_ID": "2298", "MOVED_TIME": "2026-07-01T10:00:00+04:00",
    crm_fields.FIELD_BOT_STATUS: "", crm_fields.FIELD_ACTIVITY: "", crm.FIELD_MEETING_AT: "",
}
# Lead 79641 (chat 42): a Property Finder lead of the day before, Option Sent by agent 2298 at 09:19 the same morning.
LEAD_42 = {**IDLE_LEAD, "ID": "79641", "STATUS_ID": "UC_ZQMREH", "DATE_CREATE": iso(NOW - DAY), "MOVED_BY_ID": "2298", "MOVED_TIME": iso(NOW.replace(hour=9, minute=19))}
# The other leads closed on the launch day each had an agent's open to-do (completed in the same second as the move).
TODO_116 = {"ID": "175279", "SUBJECT": "Follow up", "COMPLETED": "N", "RESPONSIBLE_ID": "2298", "AUTHOR_ID": "1", "CREATED": "2026-10-01T10:00:00+04:00"}
TODO_118 = {"ID": "174011", "SUBJECT": "Call back", "COMPLETED": "N", "RESPONSIBLE_ID": "2302", "AUTHOR_ID": "1", "CREATED": "2026-09-30T10:00:00+04:00"}
TODO_120 = {"ID": "174899", "SUBJECT": "Follow up", "COMPLETED": "N", "RESPONSIBLE_ID": "2392", "AUTHOR_ID": "1", "CREATED": "2026-09-29T10:00:00+04:00"}


class FakeBitrix:
    """apps.crmlink.client.call, answering as the portal: the lead, its open activities, its newest activities and
    timeline comments. ``fail``: the methods that raise a passing failure (the REST throttle's 429)."""

    def __init__(self, lead=None, open_activities=(), activities=(), comments=(), fail=()):
        self.lead = dict(IDLE_LEAD if lead is None else lead)
        self.open = list(open_activities)
        self.activities = list(activities) or list(open_activities)
        self.comments = list(comments)
        self.fail = set(fail)
        self.calls = []

    def __call__(self, method, payload=None):
        self.calls.append((method, payload or {}))
        if method in self.fail:
            raise client.BitrixTransient(f"{method}: HTTP 429, the portal answered with something that is not JSON")
        if method == "crm.lead.get":
            return dict(self.lead)
        if method == "crm.activity.list":
            return list(self.open) if (payload or {}).get("filter", {}).get("COMPLETED") == "N" else list(self.activities)
        if method == "crm.timeline.comment.list":
            return list(self.comments)
        raise AssertionError(f"no {method} on Bitrix here")

    def methods(self):
        return [method for method, _ in self.calls]


class CrmWritesBase(ShopsBase):
    def queue(self, writes):
        with self.captureOnCommitCallbacks(execute=True):
            return crm_fields.queue(self.conversation, self.chat, writes)

    def write(self, ids, bitrix=None, answer=None):
        """write_crm_fields on these rows with Bitrix faked; returns (the bodies posted, the fake)."""
        bitrix = bitrix if bitrix is not None else FakeBitrix()
        posted = []
        with patch("apps.crmlink.client.call", side_effect=bitrix), patch(
            "apps.leadai.assistant.crm_fields.post", side_effect=lambda body: posted.append(body) or (answer or {"ok": True})
        ):
            tasks.write_crm_fields.apply(args=[ids])
        return posted, bitrix

    def row(self, field):
        return LeadAiCrmField.objects.filter(conversation=self.conversation, field=field).order_by("-pk").first()


# A. A shops "no": Bot Status Lost always, the stage only for a lead nobody works ---------------------------------


class LostJudgeTests(CrmWritesBase):
    """What keeps a lead in its stage, read from what Bitrix answers (pure)."""

    def test_the_launch_leads_each_had_a_reason_to_stay(self):
        system = lost.SYSTEM_USERS
        # Chat 42: a lead of the day before (a new inquiry), Option Sent by agent 2298 that morning.
        self.assertEqual(lost.judge_lead(LEAD_42, NOW, system), "it came in on 11 Oct, less than 7 days ago")
        self.assertEqual(lost.judge_lead({**LEAD_42, "DATE_CREATE": IDLE_LEAD["DATE_CREATE"]}, NOW, system), "Bitrix user 2298 moved its stage on 12 Oct")
        # Chats 116, 118 and 120: an agent's open to-do, which the move would have closed.
        self.assertEqual(lost.judge_open([TODO_116]), "it has an open to-do (Follow up, Bitrix user 2298)")
        self.assertEqual(lost.judge_open([TODO_118]), "it has an open to-do (Call back, Bitrix user 2302)")
        self.assertEqual(lost.judge_open([TODO_120]), "it has an open to-do (Follow up, Bitrix user 2392)")
        # 52, 118 and 119 were reopened by a person; a lead booked by one is never moved either.
        self.assertEqual(lost.judge_lead({**IDLE_LEAD, "STATUS_ID": "10"}, NOW, system), "it has a meeting (Meeting/Viewing Scheduled)")
        self.assertEqual(lost.judge_lead({**IDLE_LEAD, crm.FIELD_MEETING_AT: "2026-10-13T18:00:00+04:00"}, NOW, system), "it has a meeting time")
        self.assertEqual(lost.judge_lead({**IDLE_LEAD, "STATUS_ID": "1"}, NOW, system), "it is in a closed stage already (Not Interested)")
        self.assertEqual(lost.judge_lead({**IDLE_LEAD, "STATUS_SEMANTIC_ID": "S", "STATUS_ID": "CONVERTED"}, NOW, system), "it is in a closed stage already (CONVERTED)")
        # A person's field edit, or their last timeline activity, in the last seven days.
        edited = {**IDLE_LEAD, "MODIFY_BY_ID": "2302", "DATE_MODIFY": iso(NOW - 3 * DAY)}
        self.assertEqual(lost.judge_lead(edited, NOW, system), "Bitrix user 2302 changed it on 09 Oct")
        worked = {**IDLE_LEAD, "LAST_ACTIVITY_BY": "2392", "LAST_ACTIVITY_TIME": iso(NOW - 6 * DAY)}
        self.assertEqual(lost.judge_lead(worked, NOW, system), "Bitrix user 2392 worked on it on 06 Oct")

    def test_an_idle_lead_has_none_and_our_own_writes_are_nobodys_work(self):
        system = lost.SYSTEM_USERS | {"2600"}
        self.assertEqual(lost.judge_lead(IDLE_LEAD, NOW, system), "")
        # Our own: the Lead fields tool (user 1) and the REST webhook's user (the mirror); a person eight days ago.
        ours = {**IDLE_LEAD, "LAST_ACTIVITY_BY": "2600", "LAST_ACTIVITY_TIME": iso(NOW - dt.timedelta(minutes=5))}
        self.assertEqual(lost.judge_lead(ours, NOW, system), "")
        old = {**IDLE_LEAD, "MODIFY_BY_ID": "2298", "DATE_MODIFY": iso(NOW - 8 * DAY)}
        self.assertEqual(lost.judge_lead(old, NOW, system), "")
        done = [{"ID": "1", "SUBJECT": "Follow up", "COMPLETED": "Y", "AUTHOR_ID": "2298", "EDITOR_ID": "1", "CREATED": iso(NOW - 30 * DAY), "LAST_UPDATED": iso(NOW - DAY)}]
        self.assertEqual(lost.judge_open(done), "")
        self.assertEqual(lost.judge_activities(done, NOW, system), "")  # completed by our own move (user 1)
        mirror = [{"ID": "9", "AUTHOR_ID": "2600", "CREATED": iso(NOW - DAY)}, {"ID": "8", "AUTHOR_ID": "1", "CREATED": iso(NOW - DAY)}]
        self.assertEqual(lost.judge_comments(mirror, NOW, system), "")
        self.assertEqual(lost.judge_comments({"items": mirror}, NOW, system), "")

    def test_a_persons_activity_or_comment_this_week_keeps_it(self):
        call = [{"ID": "3", "SUBJECT": "Outgoing call", "COMPLETED": "Y", "AUTHOR_ID": "2298", "CREATED": iso(NOW - 2 * DAY), "LAST_UPDATED": iso(NOW - 2 * DAY)}]
        self.assertEqual(lost.judge_activities(call, NOW, lost.SYSTEM_USERS), "Bitrix user 2298 worked on it on 10 Oct (Outgoing call)")
        note = [{"ID": "4", "AUTHOR_ID": "2302", "CREATED": iso(NOW - DAY)}]
        self.assertEqual(lost.judge_comments(note, NOW, lost.SYSTEM_USERS), "Bitrix user 2302 wrote on its timeline on 11 Oct")

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/2600/abcdef/")
    def test_the_webhooks_own_user_is_ours(self):
        self.assertEqual(lost.system_users(), lost.SYSTEM_USERS | {"2600"})
        with override_settings(BITRIX_WEBHOOK_URL=""):
            self.assertEqual(lost.system_users(), lost.SYSTEM_USERS)


class LostMoveTests(CrmWritesBase):
    """write_crm_fields with a shops no's rows: the move goes only to a lead nobody works."""

    def no(self, words="No"):
        return self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, words))

    def test_an_idle_lead_moves_with_the_reason(self):
        ids = self.no()
        posted, bitrix = self.write(ids)
        self.assertEqual(posted, [{"lead_id": 555, "fields": {STATUS: 2480}, "lost": {"status_id": "1", "reason": "No"}}])
        self.assertEqual(bitrix.methods(), ["crm.lead.get", "crm.activity.list", "crm.activity.list", "crm.timeline.comment.list"])
        self.assertTrue(all(row.sent_at and row.error == "" for row in LeadAiCrmField.objects.all()))

    def test_an_open_to_do_keeps_the_lead_and_every_to_do_as_it_is(self):
        for todo, owner in ((TODO_116, "2298"), (TODO_118, "2302"), (TODO_120, "2392")):
            with self.subTest(todo=todo["ID"]):
                LeadAiCrmField.objects.all().delete()
                ids = self.no()
                posted, bitrix = self.write(ids, FakeBitrix(open_activities=[todo]))
                body = posted[0]
                self.assertNotIn("lost", body)  # no move: Bitrix closes a lost lead's open to-dos
                self.assertEqual(body["fields"], {STATUS: 2480})  # Bot Status Lost goes all the same
                self.assertIn(f"not moved to Not Interested, because it has an open to-do ({todo['SUBJECT']}, Bitrix user {owner})", body["comment"])
                self.assertIn("No to-do was closed or changed.", body["comment"])
                self.assertIn("(No)", body["comment"])  # the customer's words
                kept = self.row(MOVE)
                self.assertTrue(kept.sent_at)
                self.assertTrue(kept.error.startswith(lost.NOT_MOVED + "it has an open to-do"))
                self.assertNotIn("crm.timeline.comment.list", bitrix.methods())  # nothing more is read once a reason is found

    def test_a_colleagues_whatsapp_chat_keeps_it(self):
        # Chat 120 (lead 79417): agent 2392 chatted the customer about studios on another number from 11:18; the bot
        # closed the lead at 11:32. Chat 42's agent 2298 did the same in conv 37202.
        other = Conversation.objects.create(
            number=WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2"), contact=self.contact
        )
        _outbound(other, self.responsible, Message.Kind.TEXT, "We have a studio in England cluster for you", {}, created_at=NOW - dt.timedelta(minutes=14))
        posted, bitrix = self.write(self.no("No thankyou"))
        self.assertNotIn("lost", posted[0])
        self.assertIn("because a colleague wrote to the customer on WhatsApp on 12 Oct", posted[0]["comment"])
        self.assertEqual(bitrix.methods(), ["crm.lead.get"])  # the lead, for its fields; nothing more was needed
        # Our own messages, Sara's, the AI desk's and the campaign's template are nobody working them.
        Message.objects.filter(conversation=other).delete()
        _outbound(other, None, Message.Kind.TEXT, "Hi", {"source": "leadai_ai"}, created_at=NOW - DAY)
        _outbound(other, None, Message.Kind.TEXT, "Hi", {"source": "leadbot_ai"}, created_at=NOW - DAY)
        _outbound(other, None, Message.Kind.TEXT, "Hi", {"source": "ai_desk"}, created_at=NOW - DAY)
        self.assertIsNone(lost.inbox_touch(self.contact.wa_id, NOW - lost.TOUCH_WINDOW))  # the campaign's template too
        # A colleague's message eight days ago is past the window.
        _outbound(other, self.responsible, Message.Kind.TEXT, "Hello", {}, created_at=NOW - 8 * DAY)
        self.assertIsNone(lost.inbox_touch(self.contact.wa_id, NOW - lost.TOUCH_WINDOW))

    def test_the_launch_leads_stay_where_they_were(self):
        cases = {
            "79641 (chat 42)": FakeBitrix(LEAD_42),
            "79428 (chat 116)": FakeBitrix(open_activities=[TODO_116]),
            "79420 (chat 118)": FakeBitrix(open_activities=[TODO_118]),
            "79419 (chat 119)": FakeBitrix(open_activities=[{**TODO_118, "ID": "174029"}]),
            "79417 (chat 120)": FakeBitrix(open_activities=[TODO_120]),
            "79321 (chat 134)": FakeBitrix(open_activities=[{**TODO_116, "RESPONSIBLE_ID": "2219"}, {**TODO_116, "RESPONSIBLE_ID": "2390"}]),
        }
        for lead, bitrix in cases.items():
            with self.subTest(lead=lead):
                LeadAiCrmField.objects.all().delete()
                posted, _ = self.write(self.no(), bitrix)
                self.assertNotIn("lost", posted[0])
                self.assertEqual(posted[0]["fields"], {STATUS: 2480})

    def test_a_failed_read_moves_nothing(self):
        for failing in ({"crm.lead.get"}, {"crm.activity.list"}, {"crm.timeline.comment.list"}):
            with self.subTest(failing=failing):
                LeadAiCrmField.objects.all().delete()
                posted, _ = self.write(self.no(), FakeBitrix(fail=failing))
                self.assertNotIn("lost", posted[0])
                self.assertIn("because Bitrix could not be read", posted[0]["comment"])
        # The settings off: Bot Status Lost alone, never the stage.
        LeadAiCrmField.objects.all().delete()
        with patch.object(lost, "MOVE_STAGE", False):
            posted, bitrix = self.write(self.no())
        self.assertNotIn("lost", posted[0])
        self.assertIn("switched off", posted[0]["comment"])

    def test_a_wrong_number_or_spam_is_junk_by_the_same_rule(self):
        posted, _ = self.write(self.queue(crm_fields.opt_out_writes(rules.WRONG_NUMBER, "wrong number")), FakeBitrix(open_activities=[TODO_116]))
        self.assertNotIn("lost", posted[0])
        self.assertIn("not moved to Junk Lead", posted[0]["comment"])
        self.assertIn("The chat reads as a wrong number or spam (wrong number).", posted[0]["comment"])
        LeadAiCrmField.objects.all().delete()
        posted, _ = self.write(self.queue(crm_fields.opt_out_writes(rules.SPAM, "Earn money daily")))
        self.assertEqual(posted[0]["lost"]["status_id"], "JUNK")

    def test_a_passing_post_failure_decides_again_on_the_retry(self):
        ids = self.no()
        with patch("apps.crmlink.client.call", side_effect=FakeBitrix(open_activities=[TODO_116])), patch(
            "apps.leadai.assistant.crm_fields.post", side_effect=crm_fields.FieldsError("Bitrix answered 503")
        ):
            tasks.write_crm_fields.apply(args=[ids])
        self.assertFalse(LeadAiCrmField.objects.filter(sent_at__isnull=False).exists())  # nothing went: tried again later
        self.assertTrue(all(row.retry_at for row in LeadAiCrmField.objects.all()))
        posted, _ = self.write(ids)  # the to-do is done since: the lead moves now
        self.assertEqual(posted[0]["lost"], {"status_id": "1", "reason": "No"})

    def test_after_six_hours_a_move_is_nobodys_to_make_by_hand(self):
        ids = self.no()
        LeadAiCrmField.objects.filter(pk__in=ids).update(error="Bitrix answered 503", retry_at=NOW)
        LeadAiCrmField.objects.filter(pk__in=ids, field=STATUS).update(sent_at=NOW)  # Bot Status went; the move did not
        self.later(6 * 60 + 1)
        tasks._retry_crm_fields()
        self.assertFalse(LeadAiAlert.objects.filter(kind="crm_failed").exists())  # never "please set it by hand"
        self.assertEqual(self.row(MOVE).error, lost.NOT_MOVED + "Bitrix could not be reached for six hours.")

    def test_without_the_guard_the_launch_lead_and_its_to_do_would_close(self):
        # As live: no read, the move goes, and Bitrix completes the agent's to-do in the same second.
        with patch("apps.leadai.assistant.lost.may_move", return_value=lost.Decision(True)):
            posted, _ = self.write(self.no(), FakeBitrix(open_activities=[TODO_120]))
        self.assertEqual(posted[0]["lost"], {"status_id": "1", "reason": "No"})


class LostTurnTests(CrmWritesBase):
    """A shops no from a turn: the rows, the note and the alert to the lead's owner and the Lead AI alert list."""

    def setUp(self):
        super().setUp()
        self.list_matloob()
        self.set_state(responsible_bitrix_user_id="2298", responsible_checked_at=NOW - dt.timedelta(hours=1))

    def check_back_no(self, words="No"):
        self.turn(self.tap("Not now"), [shop_answer()])
        self.later(2)
        return self.turn(self.inbound(words, seconds_ago=10), [shop_answer()])

    def test_chat_116_no_to_the_check_back_tells_the_owner_and_the_list(self):
        outcome, calls, _, note_delay = self.check_back_no()
        self.assertEqual((calls, self.body(outcome)), ([], "No problem, thank you for letting us know."))
        self.assertEqual(self.fields()[-2:], [(STATUS, "2480"), (MOVE, "1")])  # the move is decided when the rows go
        note_delay.assert_called_once_with(self.conversation.pk, "not_interested")
        alerts = LeadAiAlert.objects.filter(kind="lost")
        self.assertEqual({row.bitrix_user_id for row in alerts}, {"77", "2298", "2311"})  # chat owner, lead's owner, 2311
        alert = alerts.first()
        self.assertEqual(alert.title, "Ahmed Khan said no to the shops offer")
        for line in ("Their words: No", "Lead: 555", "Bot Status is now Lost in Bitrix", "no to-do is closed or changed"):
            self.assertIn(line, alert.text)

    def test_no_thankyou_in_one_word_is_codes_no_too(self):
        # Chat 120: "No thankyou" slipped past the rule and went to the model (turn 120); the outcome was the same.
        self.assertTrue(rules.is_refusal("No thankyou"))
        self.assertEqual(rules.opt_out_from_text("No thankyou"), rules.NOT_INTERESTED)
        for words in ("no thanku", "No thank u", "no thx", "No thnx"):
            with self.subTest(words=words):
                self.assertEqual(rules.opt_out_from_text(words), rules.NOT_INTERESTED)
        self.assertTrue(rules.is_acknowledgement("ok thankyou"))
        outcome, calls, _, _ = self.check_back_no("No thankyou")
        self.assertEqual((calls, self.body(outcome)), ([], "No problem, thank you for letting us know."))
        self.assertEqual(self.row(MOVE).payload, {"reason": "No thankyou"})
        self.assertTrue(LeadAiAlert.objects.filter(kind="lost", text__contains="Their words: No thankyou").exists())

    def test_already_rented_then_no_says_so(self):
        self.turn(
            self.inbound("Thanks but I already rented a shop last month"),
            [shop_answer("Congratulations on your new shop! Do you need a second one, or know someone who does?", facts={"already_rented": True})],
        )
        self.later(2)
        self.turn(self.inbound("No", seconds_ago=10), [shop_answer()])
        alert = LeadAiAlert.objects.filter(kind="lost").first()
        self.assertIn("They already rented a shop elsewhere, and said no to a second one.", alert.text)

    def test_no_alert_where_nothing_is_lost(self):
        # A customer who wants no shop to rent is never Lost (the owner's rule): no row, no alert.
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="model", words="No", playbook="ic_shops")
        self.assertFalse(LeadAiCrmField.objects.exists())
        self.assertFalse(LeadAiAlert.objects.filter(kind="lost").exists())
        # A quiet chat (the assistant off for this customer): the fields, never an alert.
        LeadAiChatState.objects.filter(conversation=self.conversation).update(not_interested_at=None, facts={})
        with self.captureOnCommitCallbacks(execute=True):
            engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="rule", quiet=True, words="No", playbook="ic_shops")
        self.assertEqual(len(self.fields()), 2)
        self.assertFalse(LeadAiAlert.objects.filter(kind="lost").exists())
        # A general chat writes no Bitrix fields and raises no such alert, as before.
        LeadAiChatState.objects.filter(conversation=self.conversation).update(not_interested_at=None)
        LeadAiCrmField.objects.all().delete()
        engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="model", words="No", playbook="general")
        self.assertFalse(LeadAiCrmField.objects.exists())
        self.assertFalse(LeadAiAlert.objects.filter(kind="lost").exists())


# B. The lead's fields: nothing it holds already; a business is a business ---------------------------------------


class HeldFieldsTests(CrmWritesBase):
    def test_a_value_the_lead_holds_is_never_posted_again(self):
        # Lead 79341 (chat 132): Bot Status Qualifying, and the change log showed "Qualifying -> (empty)" in the same
        # second as the set. Lead 78833 (chat 91): Business Activity likewise. A write of what is there is no write.
        ids = self.queue([(STATUS, crm_fields.STATUS_QUALIFYING, {}), (crm_fields.FIELD_ACTIVITY, "restaurant or cafeteria", {"only_if_empty": True})])
        bitrix = FakeBitrix({**IDLE_LEAD, STATUS: "2476", crm_fields.FIELD_ACTIVITY: "restaurant or cafeteria"})
        posted, _ = self.write(ids, bitrix)
        self.assertEqual(posted, [])
        self.assertTrue(all(row.sent_at and row.error == crm_fields.HELD_ALREADY for row in LeadAiCrmField.objects.all()))
        # The lead's own business, whatever it says, is kept: only_if_empty, so nothing to post either.
        LeadAiCrmField.objects.all().delete()
        posted, _ = self.write(self.queue([(crm_fields.FIELD_ACTIVITY, "cafe", {"only_if_empty": True})]), FakeBitrix({**IDLE_LEAD, crm_fields.FIELD_ACTIVITY: "Restaurant"}))
        self.assertEqual(posted, [])

    def test_a_change_is_posted_and_a_failed_read_posts_everything(self):
        ids = self.queue([(STATUS, crm_fields.STATUS_QUALIFYING, {}), (crm_fields.FIELD_SHOP_TYPE, 2471, {})])
        posted, _ = self.write(ids, FakeBitrix({**IDLE_LEAD, STATUS: "2476", crm_fields.FIELD_SHOP_TYPE: "2472"}))
        self.assertEqual(posted, [{"lead_id": 555, "fields": {crm_fields.FIELD_SHOP_TYPE: 2471}}])
        LeadAiCrmField.objects.all().delete()
        posted, _ = self.write(self.queue([(STATUS, crm_fields.STATUS_QUALIFYING, {})]), FakeBitrix(fail={"crm.lead.get"}))
        self.assertEqual(posted, [{"lead_id": 555, "fields": {STATUS: 2476}}])

    def test_what_holds(self):
        row = LeadAiCrmField(field=STATUS, value="2476", payload={})
        self.assertTrue(crm_fields.holds({STATUS: "2476"}, row))
        self.assertTrue(crm_fields.holds({STATUS: 2476}, row))
        self.assertFalse(crm_fields.holds({STATUS: "2477"}, row))
        self.assertFalse(crm_fields.holds({STATUS: ""}, row))
        self.assertFalse(crm_fields.holds({}, row))  # a field the answer does not carry is never taken as held
        self.assertFalse(crm_fields.holds(None, row))  # nothing read: everything goes, as before
        self.assertTrue(crm_fields.holds({"UF_X": ["2467", "805"]}, LeadAiCrmField(field="UF_X", value="2467", payload={})))
        empty_only = LeadAiCrmField(field=crm_fields.FIELD_ACTIVITY, value="vape", payload={"only_if_empty": True})
        self.assertTrue(crm_fields.holds({crm_fields.FIELD_ACTIVITY: "Mobiles"}, empty_only))
        self.assertFalse(crm_fields.holds({crm_fields.FIELD_ACTIVITY: "0"}, empty_only))  # the tool reads "0" as empty
        self.assertFalse(crm_fields.holds({MOVE: "1"}, LeadAiCrmField(field=MOVE, value="1", payload={})))


class BusinessActivityTests(CrmWritesBase):
    def test_a_home_or_a_sentence_is_no_business(self):
        for text in (
            "apartment studio", "room", "studio", "1bhk room", "residential room", "studio apartment", "flat", "bed space",
            "Is a studio apartment with balcony suitable for your business?", "I want a shop. Can you help?",
            "we are looking for a place to open something for my family and friends business",
        ):
            with self.subTest(text=text):
                self.assertFalse(crm_facts.is_business(text))
        for text in (
            "restaurant or cafeteria", "mobile phone shop", "photo studio", "yoga studio", "Normal goods, Electronics",
            "Interior landscape, Artificial plants pots, Wall", "small dessert takeaway and production kitchen", "car showroom",
            "salon", "furniture for homes", "vape", "My clothes shop", "notary office",
        ):
            with self.subTest(text=text):
                self.assertTrue(crm_facts.is_business(text))

    def test_the_lead_never_gets_one_and_the_booking_neither(self):
        # Chats 44, 49, 57 and 68 wrote "apartment studio", "room" and "studio" to the lead's Business activity field.
        writes = crm_fields.turn_writes({}, {"business_activity": "apartment studio"}, answered=False, first=False, handover=False, broker=False, booked=False)
        self.assertEqual(writes, [])
        writes = crm_fields.turn_writes({}, {"business_activity": "vape"}, answered=False, first=False, handover=False, broker=False, booked=False)
        self.assertEqual(writes, [(crm_fields.FIELD_ACTIVITY, "vape", {"only_if_empty": True})])
        appointment = LeadAiAppointment(conversation=self.conversation, status="confirmed", starts_at=NOW + DAY, details={"business_activity": "studio"})
        self.assertNotIn("fields", crm.booking_body(555, appointment, "confirmed"))

    def test_a_chat_holding_one_from_before_shows_none(self):
        # Chats 44, 49, 57 and 68 hold such a business_activity in their facts already: never shown or said back.
        facts = {"business_activity": "apartment studio", "community": "England"}
        self.assertEqual(engine._detail_lines(facts), ["Area: England"])
        appointment = LeadAiAppointment(conversation=self.conversation, status="tentative", details=facts)
        self.assertNotIn("Business activity", crm.comment_text(appointment, "tentative"))
        self.assertEqual(nudges.bare_business("studio"), "")
        self.assertEqual(nudges.bare_business("restaurant (shawarma)"), "restaurant")
        # The recommendation never names it as their business (board T56's placeholder, filled from the facts).
        answer = schema.normalize(shop_answer("For a <their business>, Type 1 is perfect. What size do you need?").data, shops=True)
        engine.settle(answer, [], ["Hi"], 0, playbook="ic_shops", facts=facts, now=NOW)
        self.assertEqual(answer["reply"], "What size do you need?")

    def test_a_turn_records_none(self):
        # Chat 57 (a need chat): the live answer held business_activity "studio".
        self.turn(self.inbound("Is a studio allowed in the shops?"), [shop_answer("Our shops are for business use.", facts={"business_activity": "studio"})])
        self.assertIsNone(self.state().facts.get("business_activity"))
        self.assertNotIn((crm_fields.FIELD_ACTIVITY, "studio"), self.fields())


# C. A Bot Status a person set in Bitrix outranks ours (issue 19, the Django side) ----------------------------------


class PersonStatusTests(CrmWritesBase):
    def test_a_person_reopening_the_lead_stops_our_pending_lost(self):
        # Leads 79382, 79419 and 79420: agent 2302 reopened them after our Lost; Bitrix now sets Handed to agent
        # (board C36), and C12 tells us. A Lost of ours still waiting for its retry must never close them again.
        ids = self.no_waiting()
        bitrix_status.apply(555, bot_status=2478, changed_by=2302, at="2026-10-12T13:50:00+04:00")
        posted, _ = self.write(ids)
        self.assertEqual(posted, [])
        for pk in ids:
            self.assertEqual(LeadAiCrmField.objects.get(pk=pk).error, "Replaced by a newer value before it was sent.")
        kept = self.row(STATUS)
        self.assertEqual((kept.value, kept.payload, kept.error), ("2478", {"set_in_bitrix": True, "changed_by": 2302}, bitrix_status.SET_IN_BITRIX))
        self.assertTrue(kept.sent_at)  # never posted
        # The next no of theirs is news again: Bot Status Lost and the move are queued (and judged when they go).
        self.assertEqual(len(self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, "No"))), 2)

    def no_waiting(self):
        ids = self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, "No"))
        LeadAiCrmField.objects.filter(pk__in=ids).update(error="Bitrix answered 503", retry_at=NOW + dt.timedelta(minutes=15))
        return ids

    def test_the_same_status_is_kept_once_and_another_lead_is_not_ours(self):
        bitrix_status.apply(555, bot_status=2478, changed_by=2302)
        bitrix_status.apply(555, bot_status=2478, changed_by=2302)
        self.assertEqual(LeadAiCrmField.objects.filter(field=STATUS).count(), 1)
        self.assertEqual(bitrix_status.remember(self.chat, 777, 2480, None, 2302, NOW), [])  # this chat writes to 555
        self.assertTrue(crm_fields.has_status(self.conversation, self.chat))  # no Qualifying over a person's status


# D. Notes are the customer's own questions; a budget of ours is not theirs ------------------------------------


# The launch chats' notes, with the customer's own words and ours (chat_<id>.json: state.facts.notes, the messages).
LAUNCH_NOTES = {
    42: (
        ["Is the shop for yourself, or are you checking for a client?", "What business the shop is for?", "What size do you need?",
         "What is your yearly budget?", "What licence kind do you have or need?", "Do you want to buy a shop or rent one?",
         "Currently only shops for rent, not sale"],
        ["To buy", "Myself", "Wat is 33000/year", "48000/year", "You are not getting I feel\n\nI want purchase shop\nNot to rent",
         "Do u understand now", "Sorry nobody\nI want to purchase shop"],
        ["Thanks for clarifying. Currently, we only have shops available for rent, not for sale. Are you interested in renting a shop instead?"],
        [],
    ),
    44: (["fit-out requirements", "parking availability"], ["I need an apartment studio"], [], []),
    49: (["size needed", "budget", "licence kind"], ["I need room\n1bhk Englund x cluster"], [], []),
    50: (["Is a room available for rent?"], ["No shop", "Looking for a room"], [], ["Is a room available for rent?"]),
    52: (["Is the shop for yourself, or are you checking for a client?"], ["I dont need shops"], [], []),
    57: (["monthly rent details"], ["am looking for studio for monthly rent sir"], [], ["monthly rent details"]),
    59: (
        ["service charge", "DEWA", "parking", "fit-out", "rent security deposit"],
        ["Yes, show me shops", "How many square feet area", "And give me full details including rent security"],
        ["Rent security is usually a deposit, and payment is in 1 to 4 cheques. Good question — I'll have our agent confirm details "
         "like service charge, DEWA, parking, and fit-out at the viewing."],
        ["rent security deposit"],
    ),
    62: (["service charge", "DEWA", "parking", "fit-out"], ["I need 600sqf", "New", "One"], [], []),
    78: (
        ["business activity", "size needed", "budget", "licence kind", "back area details", "parking availability"],
        ["For me", "How much is yur shop", "And can u give me the detai computation i need back area", "Parking side", "33k"],
        [],
        ["back area details", "parking availability"],
    ),
    88: (
        ["what business the shop is for", "size needed", "budget", "licence kind", "fit-out details", "service charge", "DEWA", "parking"],
        ["Myself", "Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft", "[tapped: Type 1 – Small]", "planning for a new one"],
        [],
        [],
    ),
    91: (
        ["What business is the shop for?", "What size of shop do you need?", "What is your budget?", "Are shops existing restaurants?",
         "Exact location of shops?", "Gas line and chimney availability"],
        ["Im actually looking for a restaurant or cafeteria", "For me", "share me the prices and spaces so i  could decide",
         "are they an existing restaurant?", "i want to know the location", "is there available gas line and chimney?"],
        [],
        ["Are shops existing restaurants?", "Exact location of shops?", "Gas line and chimney availability"],
    ),
    100: (
        # "best price" is our discount line's; half its words are his ("price"), so it stays with his own two.
        ["size needed", "budget", "licence kind", "business activity", "size or budget", "opening when", "cheaper price", "good location", "best price"],
        ["I need shop in Morroco cluster", "Ok", "Normal goods \nElectronics", "I need cheaper price no good location"],
        ["I understand. Our agent can discuss the best price for you at the viewing."],
        ["cheaper price", "good location", "best price"],
    ),
    105: (["Is residential room available?"], ["I am looking residential room"], [], ["Is residential room available?"]),
    107: (["Is a studio apartment with balcony suitable for your business?"], ["Studio apartment with balcony"], [], []),
    119: (["shop size needed", "budget", "licence kind"], ["[voice note could not be heard]"], [], []),
    120: (["What business the shop is for?"], ["Not now", "No thankyou"], [], []),
    132: (["studio availability"], ["No I didn’t ask for shop", "I asked for studio"], [], ["studio availability"]),
}


class NotesTests(CrmWritesBase):
    def test_each_launch_chat_keeps_only_its_customers_questions(self):
        for chat, (notes, theirs, ours, kept) in LAUNCH_NOTES.items():
            with self.subTest(chat=chat):
                self.assertEqual(crm_facts.their_notes(notes, theirs, ours), kept)

    def test_their_own_questions_in_any_words_stay(self):
        theirs = ["What is your commission?", "Where is your office?", "Do you have parking?", "هل يوجد موقف سيارات؟", "Is there a chiller AC?"]
        for note in ("What is your commission?", "Where is your office?", "parking", "chiller"):
            with self.subTest(note=note):
                self.assertEqual(crm_facts.their_notes([note], theirs, []), [note])
        # Chat 95's nine questions, every one of them.
        self.assertEqual(crm_facts.their_notes(list(leadai_eval.NOTES_95), [leadai_eval.NINE_QUESTIONS_95], []), list(leadai_eval.NOTES_95))
        # Arabic words for parking count; the example list never asked does not.
        self.assertEqual(crm_facts.their_notes(["parking"], ["هل يوجد موقف؟"], []), ["parking"])
        self.assertEqual(crm_facts.their_notes(["parking", "DEWA"], ["هل المحل كبير؟"], []), [])
        # The prompt's "exact unit" only when they asked which one; their "is one free?" said our way stays.
        self.assertEqual(crm_facts.their_notes(["exact unit number"], ["Is a shop free next month?"], []), [])
        self.assertEqual(crm_facts.their_notes(["exact unit number"], ["Which shop exactly will I get?"], []), ["exact unit number"])
        self.assertEqual(crm_facts.their_notes(["unit availability next month"], ["Is a shop free next month?"], []), ["unit availability next month"])

    def test_a_chat_holding_ours_from_before_shows_only_theirs(self):
        # Chat 96's facts as they stand live: ours first, then his own questions.
        notes = ["business activity", "size needed", "budget", "licence kind", "which building for 550 sq ft shop in England cluster", "is the shop open now?"]
        self.assertEqual(crm_facts.own_notes(notes), notes[4:])
        lines = engine._detail_lines({"notes": notes})
        self.assertIn("Questions for the viewing: which building for 550 sq ft shop in England cluster; is the shop open now?", lines)
        appointment = LeadAiAppointment(conversation=self.conversation, status="tentative", details={"notes": notes})
        comment = crm.comment_text(appointment, "tentative")
        self.assertIn("Questions for the viewing: which building for 550 sq ft shop in England cluster; is the shop open now?", comment)
        self.assertNotIn("licence kind", comment)
        # The next turn's merge cleans what the chat holds.
        self.assertEqual(engine._merge_facts({"notes": notes}, {"notes": []})["notes"], notes[4:])
        # Ten questions fit the comment, past safe()'s 255 characters (chat 95 asked nine).
        nine = LeadAiAppointment(conversation=self.conversation, status="tentative", details={"notes": list(leadai_eval.NOTES_95)})
        line = next(text for text in crm.comment_text(nine, "tentative").splitlines() if text.startswith("Questions for the viewing"))
        self.assertGreater(len(line), 255)
        self.assertTrue(line.endswith("complete upfront amount and fees"))

    def test_their_earlier_voice_notes_are_their_words(self):
        # Chat 96 spoke only in voice notes: "parking side par" was in an earlier one, the note came a turn later.
        voice = self.inbound("", kind=Message.Kind.AUDIO, seconds_ago=600)
        LeadAiTranscript.objects.create(message=voice, text="England cluster mein chhoti shop chahiye, 550 square feet, parking side par")
        self.ours("Aapko England cluster mein 400-550 sq ft ka shop chahiye. Kya aapke paas koi budget hai?", minutes_ago=8)
        self.turn(
            self.inbound("Kaunsi building mein hai?"),
            [shop_answer("Hamara agent viewing par building dikhayega.", language="ur_latin", facts={"notes": ["parking side shop, not front side"]})],
        )
        self.assertEqual(self.state().facts["notes"], ["parking side shop, not front side"])

    def test_a_turn_keeps_ten(self):
        self.assertEqual(schema.NOTES_MAX, 10)
        normal = schema.normalize({"facts": {"notes": list(leadai_eval.NOTES_95)}}, shops=True)
        self.assertEqual(normal["facts"]["notes"], list(leadai_eval.NOTES_95))

    def test_chat_88_turn_records_none_of_ours_and_the_alert_lists_none(self):
        # Turn 85 live ("planning for a new one"), then the call request's handover alert printed them.
        self.ours("For a shop in France cluster, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, or will you open a new one?")
        junk = RIGHT["shops-notes-theirs-88"].data["facts"]["notes"]
        self.turn(self.inbound("planning for a new one"), [shop_answer("No problem, many tenants open a new licence.", facts={"licence_kind": "new", "notes": junk})])
        self.assertFalse(self.state().facts.get("notes"))
        self.assertEqual(self.actions(Message.objects.get(body="planning for a new one"))["facts_dropped"], ["notes"])
        lines = engine._detail_lines(self.state().facts)
        self.assertFalse([line for line in lines if line.startswith("Questions for the viewing")])

    def test_chat_62_budget_of_ours_is_not_his(self):
        # Turn 76 live: budget_aed 48000 (our Type 2 "from" price) went to the tentative alert as "Budget (AED): 48000".
        self.ours("600 sq ft, got it. For that size, a Type 2 shop is perfect: 600-800 sq ft, from AED 48,000 a year.")
        self.turn(self.inbound("How much sqf"), [shop_answer("Type 2 is 600-800 sq ft.", facts={"budget_aed": 48000, "budget_basis": "per_year"})])
        facts = self.state().facts
        self.assertIsNone(facts.get("budget_aed"))
        self.assertIsNone(facts.get("budget_basis"))
        # A budget they wrote ("33k", chat 78) stays, even when it is one of our figures.
        self.assertFalse(crm_facts.budget_of_ours(33000, ["33k"], None))
        self.assertFalse(crm_facts.budget_of_ours(50000, [], None))  # not one of ours
        self.assertTrue(crm_facts.budget_of_ours(48000.0, ["How much sqf"], None))

    def test_the_prompt_lists_no_examples_to_copy(self):
        from apps.leadai.assistant import prompt

        self.assertNotIn("the exact unit, service charge, DEWA, chiller, parking", prompt.SHOPS_SYSTEM)
        self.assertNotIn("service charge, DEWA, parking", str(schema.SHOPS_SCHEMA["properties"]["facts"]["properties"]["notes"]))
        self.assertIn("never your own questions", schema.SHOPS_SCHEMA["properties"]["facts"]["properties"]["notes"]["description"])

    def test_without_the_guard_ours_reach_the_record(self):
        with patch("apps.leadai.assistant.crm_facts.settle", return_value=[]):
            junk = RIGHT["shops-notes-theirs-88"].data["facts"]["notes"]
            self.turn(self.inbound("planning for a new one"), [shop_answer("No problem, many tenants open a new licence.", facts={"notes": junk})])
        self.assertIn("fit-out details", self.state().facts["notes"])  # as live; own_notes alone leaves the example list


# E. Names: no job title, the case put right, never "Customer: -" ----------------------------------------------------


class NameTests(CrmWritesBase):
    def test_who_is_greeted(self):
        cases = {
            "MANAGER": "", "Manager": "", "SALES MANAGER": "", "Road": "", "Owner": "", "Manager Ahmed": "Ahmed",
            "kamalraafat": "Kamalraafat", "ora": "Ora", "huzefa": "Huzefa", "saurabh": "Saurabh", "kanchan": "Kanchan",
            "ETS": "ETS", "AHMED KHAN": "Ahmed", "MD. SUMON": "Sumon", "Md Sumon": "Sumon", "McDonald": "McDonald", "محمد": "محمد",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(filters.first_name(raw), expected)
        self.assertEqual(filters.person_name("MANAGER"), "")
        self.assertEqual(filters.cased("kamalraafat"), "Kamalraafat")
        self.assertEqual(filters.cased("MOHAMMED ALI"), "Mohammed Ali")
        self.assertEqual(filters.cased("ETS"), "ETS")
        self.assertEqual(filters.cased("Md Sumon"), "Md Sumon")

    def test_the_assistants_own_lines(self):
        # Chat 59: the template said "Hi ETS" and the nudge "Hi Ets"; chat 42's "Hi MANAGER" is nobody's name.
        self.assertTrue(nudges.first_text("en", "ETS", now=NOW).startswith("Hi ETS,"))
        self.assertNotIn("anager", nudges.first_text("en", "MANAGER", now=NOW))
        self.assertTrue(nudges.first_text("en", "kamalraafat", now=NOW).startswith("Hi Kamalraafat,"))
        self.assertEqual(engine.name_from("MANAGER", "there", "Ahmed Khan"), "Ahmed Khan")
        self.assertEqual(engine.name_from("kamalraafat"), "Kamalraafat")

    def test_the_model_reads_no_job_title(self):
        from apps.campaigns.models import CampaignRecipient
        from apps.inbox.models import Contact

        CampaignRecipient.objects.update(name="MANAGER")
        Contact.objects.filter(pk=self.contact.pk).update(display_name="")
        self.conversation.contact.refresh_from_db()
        _, calls, _, _ = self.turn(self.inbound("What is the rent?"), [shop_answer("Type 1 is from AED 33,000 a year.")])
        self.assertIn("CUSTOMER NAME (from our records, may be wrong): not known\n", calls[0][1]["content"])
        CampaignRecipient.objects.update(name="kamalraafat")
        self.later(2)
        _, calls, _, _ = self.turn(self.inbound("And the sizes?", seconds_ago=5), [shop_answer("Type 1 is 400-550 sq ft.")])
        self.assertIn("CUSTOMER NAME (from our records, may be wrong): Kamalraafat\n", calls[0][1]["content"])

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
    def test_the_notes_name_the_customer_or_say_nothing(self):
        # Seven leads' stop and lost notes read "Customer: -" (79150, 79321, 79417, 79428, 79466, 79634, 79641).
        self.assertNotIn("Customer:", crm.note_text("not_interested", "", "971501234567"))
        self.assertIn("Customer: Kanchan\n", crm.note_text("not_interested", "Kanchan", "971501234567"))
        from apps.campaigns.models import CampaignRecipient
        from apps.inbox.models import Contact

        CampaignRecipient.objects.update(name="kanchan")
        Contact.objects.filter(pk=self.contact.pk).update(display_name="")
        with patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_crm_note(self.conversation.pk, "not_interested")
        text = comment.call_args.args[2]
        self.assertIn("Customer: Kanchan\n", text)
        self.assertNotIn("Customer: -", text)


# F. A voice note's words on the lead's timeline --------------------------------------------------------------------


class VoiceNoteTests(CrmWritesBase):
    def voice(self):
        asset = MediaAsset.objects.create(mime_type="audio/ogg; codecs=opus", downloaded=True)
        asset.file.save("note.ogg", ContentFile(b"OggS voice"), save=True)
        return self.inbound("", kind=Message.Kind.AUDIO, media=asset, seconds_ago=60)

    def test_a_heard_note_goes_on_the_timeline_once(self):
        # Chat 96's eight voice notes read only "[audio]" on lead 79652.
        message = self.voice()
        words = "Kaunsi building mein hai? Main barah saadhay barah baje ja ke check kar loon ga"
        with patch("apps.leadai.assistant.openai_client.transcribe", return_value=words), patch(
            "apps.leadai.tasks.record_voice_note.delay"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(transcribe.transcript_for(message), words)
            self.assertEqual(transcribe.transcript_for(message), words)  # heard: never sent to OpenAI or queued again
        queued.assert_called_once_with(message.pk)
        self.assertTrue(LeadAiTranscript.objects.get(message=message).heard)
        with override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/"), patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_voice_note(message.pk)
        entity, crm_id, text = comment.call_args.args
        self.assertEqual((entity, crm_id), ("lead", 555))
        self.assertEqual(text, f"WhatsApp · Customer · 12 Oct 13:59 · voice note\n{words}")

    def test_a_note_never_heard_goes_nowhere(self):
        message = self.voice()
        with patch("apps.leadai.assistant.openai_client.transcribe", side_effect=transcribe.openai_client.AssistantError("http_500")), patch(
            "apps.leadai.tasks.record_voice_note.delay"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(transcribe.transcript_for(message), "")
        queued.assert_not_called()
        with override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/"), patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_voice_note(message.pk)
        comment.assert_not_called()


# G. A shop photo with no caption stays ours (issue 25) --------------------------------------------------------------


class ShopPhotoPayloadTests(CrmWritesBase):
    def photo(self):
        return Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.IMAGE, body="", wamid="wamid.photo1",
            payload={"source": "leadai_ai", "turn": 81, "shop_media": "type_2", "shop_media_id": 7, "media_id": "m1", "gateway_kind": "image"},
            status=Message.Status.SENT, created_at=NOW - dt.timedelta(minutes=2),
        )

    ECHO = {"id": "wamid.photo1", "from": "971500000001", "type": "image", "datetime": "2026-10-12 13:58:00", "image": {"id": "x", "mime_type": "image/jpeg"}}

    def test_the_gateway_echo_keeps_our_payload(self):
        # Chat 100's four Type 2 photos (180112-180122) held only the echo, and the timeline read them as an agent's.
        asked = self.inbound("How big is it?", seconds_ago=180)
        photo = self.photo()
        ingest._hydrate_existing(photo, kind="image", preview="[image]", caption_text="", media=None, quoted=None, payload=dict(self.ECHO), sent_at=None)
        photo.refresh_from_db()
        self.assertEqual((photo.payload["source"], photo.payload["turn"], photo.payload["shop_media_id"]), ("leadai_ai", 81, 7))
        self.assertEqual(photo.payload["image"], self.ECHO["image"])  # the echo's own keys are added
        self.assertFalse(engine.human_after(asked, set()))  # no colleague answered them
        self.assertIn("· Lead AI assistant ·", crmlink_tasks._line(photo))
        # A status save reads nothing more; a colleague's message is left as it is.
        fresh = Message.objects.get(pk=photo.pk)
        with self.assertNumQueries(1):
            fresh.save(update_fields=["status"])
        theirs = _outbound(self.conversation, self.agent, Message.Kind.IMAGE, "", {"x": 1})
        theirs.payload = {"y": 2}
        theirs.save(update_fields=["payload"])
        theirs.refresh_from_db()
        self.assertEqual(theirs.payload, {"y": 2})

    def test_without_the_guard_it_reads_as_a_colleagues(self):
        from django.db.models.signals import pre_save

        from apps.leadai import signals

        pre_save.disconnect(signals.keep_own_payload, sender=Message, dispatch_uid="leadai_keep_own_payload")
        self.addCleanup(pre_save.connect, signals.keep_own_payload, sender=Message, dispatch_uid="leadai_keep_own_payload")
        asked = self.inbound("How big is it?", seconds_ago=180)
        photo = self.photo()
        ingest._hydrate_existing(photo, kind="image", preview="[image]", caption_text="", media=None, quoted=None, payload=dict(self.ECHO), sent_at=None)
        photo.refresh_from_db()
        self.assertNotIn("source", photo.payload)
        self.assertTrue(engine.human_after(asked, set()))
        self.assertIn("· Agent ·", crmlink_tasks._line(photo))


# H. The new eval scenarios fail without their guards ----------------------------------------------------------------


class EvalScenarioTests(CrmWritesBase):
    def run_with(self, scenario_id, completion):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion):
            return leadai_eval.run_once(scenario, scenario_id)

    def test_they_pass_with_the_live_answers_and_fail_without_the_guards(self):
        for scenario_id in ("shops-notes-theirs-88", "shops-budget-ours-62", "shops-nine-questions-noted-95", "shops-no-thankyou-120"):
            with self.subTest(scenario_id=scenario_id):
                self.assertEqual(self.run_with(scenario_id, RIGHT[scenario_id]).failures, [])
        with patch("apps.leadai.assistant.crm_facts.settle", return_value=[]), patch("apps.leadai.assistant.crm_facts.own_notes", side_effect=lambda notes: notes):
            self.assertIn("facts.notes holds what they never asked", self.run_with("shops-notes-theirs-88", RIGHT["shops-notes-theirs-88"]).failures[0])
            failures = self.run_with("shops-budget-ours-62", RIGHT["shops-budget-ours-62"]).failures
            self.assertTrue(any("facts.budget_aed 48000" in failure for failure in failures), failures)
        # A cap of five loses four of his nine, unless code notes his must-answer questions in his words (the launch gate's
        # crm_facts.their_questions, which test_launch_gate proves on its own): with both off, they are lost.
        with patch.object(schema, "NOTES_MAX", 5), patch.object(crm_facts, "THEIR_QUESTIONS_NOTED", False):
            failures = self.run_with("shops-nine-questions-noted-95", RIGHT["shops-nine-questions-noted-95"]).failures
        self.assertTrue(any("lost their own question" in failure for failure in failures), failures)
        # "No thankyou" without the new spellings is the model's again (code_first settles nothing).
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == "shops-no-thankyou-120")
        with patch.object(rules, "PHRASE_INDEX", {key: value for key, value in rules.PHRASE_INDEX.items() if "thankyou" not in key}), patch.object(
            rules, "FILLERS", tuple(word for word in rules.FILLERS if word != "thankyou")
        ), patch.object(rules, "REFUSALS", {phrase for phrase in rules.REFUSALS if "thankyou" not in phrase}):
            self.assertIsNone(leadai_eval.code_first(scenario))
        self.assertEqual(leadai_eval.code_first(scenario)["opt_out"], rules.NOT_INTERESTED)


class PeopleLinesStillHoldTests(CrmWritesBase):
    """The must-answer questions of chat 95 still reach a person listed, now all of them noted (the chat goes on: batch
    2d's review, people.MUST_ANSWER_PAUSES False)."""

    def test_chat_95(self):
        self.list_matloob()
        outcome, _, _, _ = self.turn(
            self.inbound(leadai_eval.NINE_QUESTIONS_95),
            [shop_answer("Thank you. Our agent will answer them here.", handover="legal_visa_licence_contract", facts={"notes": list(leadai_eval.NOTES_95)})],
        )
        self.assertEqual(self.body(outcome), people.line(people.MUST_ANSWER, "en", shops=True))
        self.assertEqual(self.state().facts["notes"], list(leadai_eval.NOTES_95))
        self.assertIsNone(LeadAiTurn.objects.get().actions.get("facts_dropped"))
        alert = LeadAiAlert.objects.filter(kind=people.QUESTIONS, bitrix_user_id="2311").first()
        self.assertIn("Questions for the viewing: NOC for F&B;", alert.text)
        self.assertIn("complete upfront amount and fees", alert.text)
