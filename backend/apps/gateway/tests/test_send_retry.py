from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.gateway.client import AlotsClient, AlotsError, _is_transient_send_failure


class SendRetryTests(SimpleTestCase):
    def setUp(self):
        self.client = AlotsClient(
            api_key="test-alots-key",
            base_url="https://alots.io",
            version="v23.0",
        )

    def test_html_404_is_transient(self):
        self.assertTrue(
            _is_transient_send_failure(AlotsError("HTTP 404", status_code=404, payload=None))
        )

    def test_meta_json_404_is_not_transient(self):
        self.assertFalse(
            _is_transient_send_failure(
                AlotsError(
                    "Unsupported post request",
                    status_code=404,
                    payload={"error": {"message": "Unsupported post request"}},
                )
            )
        )

    @patch("apps.gateway.client.time.sleep")
    def test_html_404_retries_once(self, sleep):
        html_404 = AlotsError(
            "The WhatsApp provider was briefly unreachable. Send the message again.",
            status_code=404,
            payload=None,
        )
        ok = {"messages": [{"id": "wamid.ok"}]}
        with patch.object(self.client, "_request", side_effect=[html_404, ok]) as req:
            body = self.client.send_raw("772479489292535", {"type": "text"})
        self.assertEqual(body, ok)
        self.assertEqual(req.call_count, 2)
        sleep.assert_called_once()

    @patch("apps.gateway.client.time.sleep")
    def test_json_404_is_not_retried(self, sleep):
        meta_404 = AlotsError(
            "Unsupported post request",
            status_code=404,
            payload={"error": {"message": "Unsupported post request"}},
        )
        with patch.object(self.client, "_request", side_effect=meta_404) as req:
            with self.assertRaises(AlotsError):
                self.client.send_raw("772479489292535", {"type": "text"})
        self.assertEqual(req.call_count, 1)
        sleep.assert_not_called()

    @patch("apps.gateway.client.time.sleep")
    def test_internal_500_retries_without_plus(self, sleep):
        boom = AlotsError(
            "The WhatsApp provider had an internal error. Send the message again.",
            status_code=500,
        )
        ok = {"contacts": [{"wa_id": "923078633218"}], "messages": [{"id": "wamid.ok"}]}
        payload = {"to": "+923078633218", "type": "text"}
        with patch.object(self.client, "_request", side_effect=[boom, ok]) as req:
            body = self.client.send_raw("1268836452972273", payload)
        self.assertEqual(body, ok)
        self.assertEqual(req.call_args_list[1].kwargs["json"]["to"], "923078633218")
        sleep.assert_called()

    def test_html_404_sentence_for_agents(self):
        html = MagicMock(
            status_code=404,
            content=b"<!DOCTYPE HTML>",
            text='<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">',
        )
        html.json.side_effect = ValueError("not json")
        with patch("apps.gateway.client.ApiCall.save"):
            with patch("apps.gateway.client.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.return_value = html
                with self.assertRaises(AlotsError) as raised:
                    self.client._request("POST", "/v23.0/772479489292535/messages", json={})
        self.assertIn("briefly unreachable", str(raised.value))
        self.assertIsNone(raised.value.payload)
