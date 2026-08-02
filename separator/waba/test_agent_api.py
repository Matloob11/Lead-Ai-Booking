"""
BE-05: tests for the agent widget REST API (Frontend Session 2).

Kept separate from `tests.py`, which covers the SessionWindow model and the Bitrix
placement action, so the two surfaces can evolve independently.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from separator.waba.models import Phone, SessionWindow, Template, Waba

User = get_user_model()


class AgentApiTestBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw-owner-123")
        self.stranger = User.objects.create_user(email="stranger@example.com", password="pw-stranger-123")

        self.waba = Waba.objects.create(waba_id="waba-1", access_token="token-1")
        self.phone = Phone.objects.create(
            phone="+15550001111",
            phone_id="pnid-1",
            waba=self.waba,
            owner=self.owner,
        )
        self.customer = "+79991234567"

    def login_owner(self):
        self.client.force_login(self.owner)


class SessionWindowStatusApiTests(AgentApiTestBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("waba-session-window")

    def test_requires_authentication(self):
        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": self.customer})
        self.assertIn(response.status_code, (401, 403))

    def test_unknown_customer_reports_closed(self):
        self.login_owner()
        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": self.customer})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["open"])
        self.assertFalse(body["can_send_freeform"])
        self.assertTrue(body["can_send_template"])
        self.assertEqual(body["remaining_seconds"], 0)
        self.assertIsNone(body["last_inbound_at"])

    def test_open_window_reports_countdown(self):
        SessionWindow.touch(self.phone, self.customer)
        self.login_owner()

        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": self.customer})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["open"])
        self.assertTrue(body["can_send_freeform"])
        self.assertGreater(body["remaining_seconds"], 0)
        self.assertLessEqual(body["remaining_seconds"], 24 * 3600)
        self.assertIsNotNone(body["expires_at"])

    def test_expired_window_reports_closed(self):
        SessionWindow.touch(self.phone, self.customer, when=timezone.now() - timedelta(hours=25))
        self.login_owner()

        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": self.customer})

        body = response.json()
        self.assertFalse(body["open"])
        self.assertFalse(body["can_send_freeform"])
        self.assertEqual(body["remaining_seconds"], 0)

    def test_accepts_unformatted_customer_number(self):
        SessionWindow.touch(self.phone, self.customer)
        self.login_owner()

        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": "7 999 123-45-67"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["open"])

    def test_missing_customer_phone_is_rejected(self):
        self.login_owner()
        response = self.client.get(self.url, {"phone_id": "pnid-1"})
        self.assertEqual(response.status_code, 400)

    def test_missing_phone_id_is_rejected(self):
        self.login_owner()
        response = self.client.get(self.url, {"customer_phone": self.customer})
        self.assertEqual(response.status_code, 400)

    def test_unknown_phone_returns_404(self):
        self.login_owner()
        response = self.client.get(self.url, {"phone_id": "nope", "customer_phone": self.customer})
        self.assertEqual(response.status_code, 404)

    def test_other_users_phone_is_forbidden(self):
        self.client.force_login(self.stranger)
        response = self.client.get(self.url, {"phone_id": "pnid-1", "customer_phone": self.customer})
        self.assertEqual(response.status_code, 403)

    @override_settings(WABA_SESSION_WINDOW_HOURS=1)
    def test_window_hours_setting_is_reported_and_applied(self):
        SessionWindow.touch(self.phone, self.customer, when=timezone.now() - timedelta(hours=2))
        self.login_owner()

        body = self.client.get(
            self.url, {"phone_id": "pnid-1", "customer_phone": self.customer}
        ).json()

        self.assertEqual(body["window_hours"], 1)
        self.assertFalse(body["open"])


class AgentTemplatesApiTests(AgentApiTestBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("waba-agent-templates")
        self.approved = Template.objects.create(
            id="tmpl-approved",
            waba=self.waba,
            name="hello_world",
            lang="en_US",
            status="APPROVED",
            category="MARKETING",
            availableInB24=True,
        )
        self.rejected = Template.objects.create(
            id="tmpl-rejected",
            waba=self.waba,
            name="nope",
            lang="en_US",
            status="REJECTED",
            category="MARKETING",
            availableInB24=True,
        )

    def test_requires_authentication(self):
        self.assertIn(self.client.get(self.url, {"phone_id": "pnid-1"}).status_code, (401, 403))

    def test_lists_only_approved_templates_by_default(self):
        self.login_owner()
        body = self.client.get(self.url, {"phone_id": "pnid-1"}).json()

        self.assertEqual(body["count"], 1)
        self.assertEqual(body["templates"][0]["id"], "tmpl-approved")
        self.assertEqual(body["templates"][0]["language"], "en_US")

    def test_status_all_includes_non_approved(self):
        self.login_owner()
        body = self.client.get(self.url, {"phone_id": "pnid-1", "status": "all"}).json()
        self.assertEqual(body["count"], 2)

    def test_exposes_component_parameters_for_the_widget(self):
        from separator.waba.models import (
            TemplateComponent,
            TemplateComponentNamedParam,
            TemplateComponentPositionalParam,
        )

        component = TemplateComponent.objects.create(
            template=self.approved, type="BODY", format="TEXT", text="Hi {{1}}", index=0,
        )
        TemplateComponentNamedParam.objects.create(component=component, name="first_name")
        TemplateComponentPositionalParam.objects.create(component=component, position=1)

        self.login_owner()
        template = self.client.get(self.url, {"phone_id": "pnid-1"}).json()["templates"][0]

        self.assertEqual(template["params"]["named"], ["first_name"])
        self.assertEqual(template["params"]["positional"], [1])
        self.assertEqual(template["components"][0]["text"], "Hi {{1}}")

    def test_other_users_phone_is_forbidden(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url, {"phone_id": "pnid-1"}).status_code, 403)


class SendTemplateApiTests(AgentApiTestBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("waba-send-template")
        self.template = Template.objects.create(
            id="tmpl-approved",
            waba=self.waba,
            name="hello_world",
            lang="en_US",
            status="APPROVED",
            category="MARKETING",
            availableInB24=True,
        )

    def post(self, payload):
        return self.client.post(self.url, payload, content_type="application/json")

    def test_requires_authentication(self):
        response = self.post({
            "phone_id": "pnid-1", "customer_phone": self.customer, "template_id": "tmpl-approved",
        })
        self.assertIn(response.status_code, (401, 403))

    def test_unknown_template_returns_404(self):
        self.login_owner()
        response = self.post({
            "phone_id": "pnid-1", "customer_phone": self.customer, "template_id": "missing",
        })
        self.assertEqual(response.status_code, 404)

    def test_missing_customer_phone_is_rejected(self):
        self.login_owner()
        response = self.post({"phone_id": "pnid-1", "template_id": "tmpl-approved"})
        self.assertEqual(response.status_code, 400)

    def test_pipe_in_parameter_value_is_rejected(self):
        self.login_owner()
        response = self.post({
            "phone_id": "pnid-1",
            "customer_phone": self.customer,
            "template_id": "tmpl-approved",
            "params": {"first_name": "a|b"},
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("|", response.json()["error"])

    def test_raw_components_passthrough_is_sent_to_meta(self):
        self.login_owner()
        components = [{"type": "body", "parameters": [{"type": "text", "text": "Ali"}]}]

        with patch(
            "separator.waba.api.views.send_message_from_phone",
            return_value={"messages": [{"id": "wamid.OUT"}]},
        ) as send:
            response = self.post({
                "phone_id": "pnid-1",
                "customer_phone": self.customer,
                "template_id": "tmpl-approved",
                "components": components,
            })

        self.assertEqual(response.status_code, 200)
        sent_message = send.call_args.args[1]
        self.assertEqual(sent_message["type"], "template")
        self.assertEqual(sent_message["to"], "79991234567")
        self.assertEqual(sent_message["template"]["name"], "hello_world")
        self.assertEqual(sent_message["template"]["components"], components)

    def test_meta_error_is_surfaced_as_400(self):
        self.login_owner()
        with patch(
            "separator.waba.api.views.send_message_from_phone",
            return_value={"error": True, "message": "tariff expired"},
        ):
            response = self.post({
                "phone_id": "pnid-1",
                "customer_phone": self.customer,
                "template_id": "tmpl-approved",
                "components": [{"type": "body"}],
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("tariff expired", response.json()["error"])

    def test_sending_a_template_does_not_reopen_the_window(self):
        """Meta rule: only an inbound customer message reopens the 24h window."""
        self.login_owner()
        with patch(
            "separator.waba.api.views.send_message_from_phone",
            return_value={"messages": [{"id": "wamid.OUT"}]},
        ):
            response = self.post({
                "phone_id": "pnid-1",
                "customer_phone": self.customer,
                "template_id": "tmpl-approved",
                "components": [{"type": "body"}],
            })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["window"]["open"])
        self.assertFalse(SessionWindow.objects.filter(phone=self.phone).exists())

    def test_other_users_phone_is_forbidden(self):
        self.client.force_login(self.stranger)
        response = self.post({
            "phone_id": "pnid-1", "customer_phone": self.customer, "template_id": "tmpl-approved",
        })
        self.assertEqual(response.status_code, 403)
