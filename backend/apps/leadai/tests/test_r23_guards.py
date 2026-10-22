"""Round 23's eval-gate guards (the deployed gate's eval of 2026-10-22, run before the handover desk went live):

- a complaint the model apologised for with no handover (eval complaint, both runs: "We apologize for the inconvenience
  caused. Our specialist will contact you here soon.", handover none) is complaint_or_upset (engine.complaint_handover):
  a person has the chat and the desk shows it; not while a person has it already, not over a stop, not without the
  apology (a "worst" asked about parking is a question);
- "I will reach by 5:30" after the Running Late tap, read by the model as a reschedule to 17:30 (eval
  booked-running-late, one run of two), is their late arrival (engine.late_arrival): running_late with their time,
  code's arrival line, never a second confirmation.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
from dataclasses import replace

from django.test import SimpleTestCase, TestCase

from apps.leadai.assistant import engine, filters, rules
from apps.leadai.models import LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_eval_guard_fixes import run_scenario
from apps.leadai.tests.test_eval_guards import scenario
from apps.leadai.tests.test_shops_playbook import ShopsBase, at, shop_answer

COMPLAINT = "Your agent said she would call me this morning and nobody called. Very bad service, I wasted my whole morning waiting"
APOLOGY = "We apologize for the inconvenience caused. Our specialist will contact you here soon."
PARKING = "Which cluster is the worst for parking?"


class ComplaintHandoverTests(ShopsBase):
    def test_a_complaint_the_model_apologised_for_is_handed_over(self):
        outcome, calls, _, _ = self.turn(self.inbound(COMPLAINT), [shop_answer(APOLOGY)])
        self.assertEqual(len(calls), 1)
        state = self.state()
        self.assertEqual(state.handover_reason, "complaint_or_upset")
        self.assertIsNotNone(state.handed_over_at)
        self.assertEqual((state.desk_at, state.desk_reason), (state.handed_over_at, "complaint_or_upset"))
        self.assertTrue(self.body(outcome))

    def test_not_while_a_person_has_the_chat(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(hours=1), handover_reason="customer_asked_human")
        self.turn(self.inbound(COMPLAINT), [shop_answer(APOLOGY)])
        state = self.state()
        self.assertEqual((state.handover_reason, state.handed_over_at), ("customer_asked_human", NOW - dt.timedelta(hours=1)))

    def test_a_complaint_word_with_no_apology_hands_nobody_the_chat(self):
        self.turn(self.inbound(PARKING), [shop_answer("Parking is easiest at Russia cluster. What business will the shop be for?")])
        self.assertIsNone(self.state().handed_over_at)

    def test_the_guard_itself(self):
        answer = {"handover": {"needed": False, "reason": None}, "opt_out": "none", "send": True, "reply": APOLOGY}
        self.assertTrue(engine.complaint_handover(answer, [COMPLAINT]))
        self.assertEqual(answer["handover"], {"needed": True, "reason": "complaint_or_upset"})
        for words, reply, extra in (
            ([COMPLAINT], APOLOGY, {"quiet": True}),
            ([COMPLAINT], "Noted. What business will the shop be for?", {}),
            ([PARKING], "Parking is easiest at Russia cluster.", {}),
            (["Thanks, see you at 5"], "Sorry for the delay. See you at 5 PM.", {}),
            ([COMPLAINT], APOLOGY, {"opt_out": "stop_all"}),
            ([COMPLAINT], APOLOGY, {"send": False}),
        ):
            quiet = extra.pop("quiet", False)
            untouched = {"handover": {"needed": False, "reason": None}, "opt_out": "none", "send": True, "reply": reply, **extra}
            self.assertFalse(engine.complaint_handover(untouched, words, quiet=quiet), (words, reply, extra))
            self.assertEqual(untouched["handover"], {"needed": False, "reason": None})
        # The model's own handover, whatever it is, stays what it is.
        theirs = {"handover": {"needed": True, "reason": "call_requested"}, "opt_out": "none", "send": True, "reply": APOLOGY}
        self.assertFalse(engine.complaint_handover(theirs, [COMPLAINT]))
        self.assertEqual(theirs["handover"]["reason"], "call_requested")


class EvalMirrorTests(TestCase):
    def test_the_eval_mirrors_the_guard_and_its_quiet_exception(self):
        run, _ = run_scenario(scenario("complaint"), eval_answer(APOLOGY))
        self.assertEqual(run.answer["handover"], {"needed": True, "reason": "complaint_or_upset"})
        # A person has the chat (handed_over): the guard stands aside live (settle's quiet), so in the eval too.
        held = replace(scenario("complaint"), handed_over="yes (call_requested)")
        run, _ = run_scenario(held, eval_answer(APOLOGY))
        self.assertNotEqual((run.answer or {}).get("handover", {}).get("reason"), "complaint_or_upset")


class LateArrivalTurnTests(ShopsBase):
    def setUp(self):
        super().setUp()
        self.visit = LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", place="office", starts_at=at(12, 15),
            customer_state=LeadAiAppointment.CustomerState.RUNNING_LATE, customer_name="Ahmed Khan",
        )
        self.ours(rules.line("ask_eta", "en"), minutes_ago=2)

    def test_their_arrival_read_as_a_move_is_running_late(self):
        message = self.inbound("I will reach by 3:30")
        moved = shop_answer(
            "Thank you for letting us know. We have rescheduled your meeting to 3:30 PM today.",
            action="reschedule", place="office", date="2026-10-12", time="15:30",
        )
        outcome, calls, _, _ = self.turn(message, [moved])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), filters.arrival("en", at(12, 15, 30)))
        self.visit.refresh_from_db()
        self.assertEqual(
            (self.visit.customer_state, self.visit.eta_at, self.visit.starts_at),
            (LeadAiAppointment.CustomerState.RUNNING_LATE, at(12, 15, 30), at(12, 15, 30)),
        )


class LateArrivalGuardTests(SimpleTestCase):
    def visit(self, **fields):
        fields = {"status": "confirmed", "place": "office", "starts_at": at(12, 17), "customer_state": LeadAiAppointment.CustomerState.RUNNING_LATE, **fields}
        return LeadAiAppointment(**fields)

    def test_the_guard_itself(self):
        proposal = {"action": "reschedule", "place": "office", "date": "2026-10-12", "time": "17:30"}
        self.assertTrue(engine.late_arrival(proposal, self.visit()))
        self.assertEqual(proposal["action"], "running_late")
        same_time = {"action": "reschedule", "place": "office", "date": None, "time": "17:00"}  # the visit's own time: on time, by turn_action
        self.assertTrue(engine.late_arrival(same_time, self.visit()))
        for proposal, visit in (
            ({"action": "reschedule", "date": "2026-10-13", "time": "17:30"}, self.visit()),  # another day: a move
            ({"action": "reschedule", "date": "2026-10-12", "time": "16:30"}, self.visit()),  # before the visit: a move
            ({"action": "reschedule", "date": "2026-10-12", "time": "17:30"}, self.visit(customer_state="")),  # no Running Late tap
            ({"action": "reschedule", "date": "2026-10-12", "time": "17:30"}, self.visit(status="tentative")),
            ({"action": "confirm", "date": "2026-10-12", "time": "17:30"}, self.visit()),
            ({"action": "reschedule", "date": "2026-10-12", "time": None}, self.visit()),
        ):
            before = dict(proposal)
            self.assertFalse(engine.late_arrival(proposal, visit), (before, visit.status, visit.customer_state))
            self.assertEqual(proposal, before)
        self.assertFalse(engine.late_arrival({"action": "reschedule", "time": "17:30"}, None))
