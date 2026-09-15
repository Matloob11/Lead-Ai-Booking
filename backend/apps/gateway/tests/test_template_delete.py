from unittest.mock import MagicMock, patch

import pytest
from django.test import SimpleTestCase, override_settings

from apps.gateway.client import AlotsClient, AlotsError


class TemplateDeleteTests(SimpleTestCase):
    def setUp(self):
        self.client = AlotsClient(
            api_key="test-alots-key",
            base_url="https://alots.io",
            version="v23.0",
        )

    @patch("apps.gateway.client.ApiCall.save")
    def test_delete_falls_back_to_graph_on_gateway_405(self, _save):
        gateway_exc = AlotsError(
            "DELETE /v23.0/123/message_templates -> HTTP 405",
            status_code=405,
        )
        graph_response = MagicMock(status_code=200, content=b'{"success":true}')
        graph_response.json.return_value = {"success": True}

        with patch.object(self.client, "_request", side_effect=gateway_exc) as gateway_call:
            with patch("apps.gateway.client.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.return_value = graph_response
                with override_settings(META_GRAPH_ACCESS_TOKEN="meta-token"):
                    body = self.client.delete_template(
                        "123",
                        "hello_world",
                        meta_template_id="999",
                    )

        gateway_call.assert_called_once()
        http.request.assert_called_once()
        call = http.request.call_args
        self.assertEqual(call.args[0], "DELETE")
        self.assertEqual(
            call.args[1],
            "https://graph.facebook.com/v23.0/123/message_templates",
        )
        self.assertEqual(
            call.kwargs["params"],
            {"name": "hello_world", "hsm_id": "999"},
        )
        self.assertEqual(
            call.kwargs["headers"]["Authorization"],
            "Bearer meta-token",
        )
        self.assertEqual(body, {"success": True})

    def test_delete_405_without_graph_token_raises_helpful_error(self):
        gateway_exc = AlotsError(
            "DELETE /v23.0/123/message_templates -> HTTP 405",
            status_code=405,
        )

        with patch.object(self.client, "_request", side_effect=gateway_exc):
            with override_settings(META_GRAPH_ACCESS_TOKEN=""):
                with pytest.raises(AlotsError) as raised:
                    self.client.delete_template("123", "hello_world")

        self.assertEqual(raised.value.status_code, 405)
        self.assertIn("META_GRAPH_ACCESS_TOKEN", str(raised.value))

    def test_delete_non_405_gateway_error_is_not_retried(self):
        gateway_exc = AlotsError(
            "DELETE /v23.0/123/message_templates -> HTTP 403",
            status_code=403,
        )

        with patch.object(self.client, "_request", side_effect=gateway_exc):
            with patch("apps.gateway.client.httpx.Client") as client_cls:
                with pytest.raises(AlotsError) as raised:
                    self.client.delete_template("123", "hello_world")

        client_cls.assert_not_called()
        self.assertEqual(raised.value.status_code, 403)
