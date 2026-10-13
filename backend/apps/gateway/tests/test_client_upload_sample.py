"""Sample handle through the gateway: two calls, the ordinary key, first handle wins."""

from unittest.mock import MagicMock, patch

import pytest
from django.test import SimpleTestCase, override_settings

from apps.gateway.client import AlotsClient, AlotsError


def _response(status_code, body):
    response = MagicMock(status_code=status_code, content=b"{}", text="{}")
    response.json.return_value = body
    return response


@override_settings(ALOTS_BASE_URL="https://alots.io", ALOTS_API_KEY="key", ALOTS_VERSION="v23.0", ALOTS_TIMEOUT=10)
class UploadSampleTests(SimpleTestCase):
    @patch("apps.gateway.client.ApiCall.save")
    def test_opens_a_session_then_sends_the_bytes_and_keeps_the_first_handle(self, _save):
        client = AlotsClient()
        with patch("apps.gateway.client.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.request.side_effect = [
                _response(200, {"id": "upload:ABC?sig=S1G"}),
                _response(200, {"h": "4:a:b:FIRST" + chr(10) + "4:a:b:SECOND"}),
            ]
            handle = client.upload_sample(b"\x89PNG\r\n\x1a\nbytes", "villa.png", "image/png")

        self.assertEqual(handle, "4:a:b:FIRST")
        first, second = http.request.call_args_list
        self.assertEqual(first.args[:2], ("POST", "https://alots.io/v23.0/app/uploads"))
        self.assertEqual(
            first.kwargs["data"],
            {"file_length": "13", "file_type": "image/png", "file_name": "villa.png"},
        )
        self.assertEqual(first.kwargs["headers"]["Authorization"], "Bearer key")
        self.assertEqual(second.args[:2], ("POST", "https://alots.io/v23.0/upload:ABC"))
        self.assertEqual(second.kwargs["params"], {"sig": "S1G"})
        self.assertEqual(second.kwargs["headers"]["file_offset"], "0")
        self.assertEqual(second.kwargs["headers"]["Content-Type"], "image/png")
        self.assertEqual(second.kwargs["headers"]["Authorization"], "Bearer key")
        self.assertEqual(second.kwargs["content"], b"\x89PNG\r\n\x1a\nbytes")

    @patch("apps.gateway.client.ApiCall.save")
    def test_the_audit_row_keeps_the_route_without_the_signature(self, _save):
        client = AlotsClient()
        with patch("apps.gateway.client.httpx.Client") as client_cls, patch(
            "apps.gateway.client.ApiCall"
        ) as api_call:
            http = client_cls.return_value.__enter__.return_value
            http.request.side_effect = [
                _response(200, {"id": "upload:ABC?sig=S1G"}),
                _response(200, {"h": "4:a:b:ONE"}),
            ]
            client.upload_sample(b"x", "a.png", "image/png")
        paths = [call.kwargs["path"] for call in api_call.call_args_list]
        self.assertEqual(paths, ["/v23.0/app/uploads", "/v23.0/upload:ABC"])
        # Neither the bytes nor the session signature reach the audit table.
        self.assertIsNone(api_call.call_args_list[1].kwargs["request_body"])
        self.assertEqual(
            api_call.call_args_list[0].kwargs["request_body"],
            {"file_length": "1", "file_type": "image/png", "file_name": "a.png"},
        )

    @patch("apps.gateway.client.ApiCall.save")
    def test_no_session_is_a_clear_error(self, _save):
        client = AlotsClient()
        with patch("apps.gateway.client.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.request.side_effect = [_response(200, {"ok": True})]
            with pytest.raises(AlotsError) as raised:
                client.upload_sample(b"x", "a.png", "image/png")
        self.assertIn("upload session", str(raised.value))

    @patch("apps.gateway.client.ApiCall.save")
    def test_no_handle_is_a_clear_error(self, _save):
        client = AlotsClient()
        with patch("apps.gateway.client.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.request.side_effect = [_response(200, {"id": "upload:ABC?sig=S"}), _response(200, {})]
            with pytest.raises(AlotsError) as raised:
                client.upload_sample(b"x", "a.png", "image/png")
        self.assertIn("no media handle", str(raised.value))

    @patch("apps.gateway.client.ApiCall.save")
    def test_a_gateway_refusal_surfaces_metas_sentence(self, _save):
        client = AlotsClient()
        with patch("apps.gateway.client.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            refusal = _response(400, {"error": {"message": "(#100) Invalid file type"}})
            refusal.text = '{"error": {"message": "(#100) Invalid file type"}}'
            http.request.side_effect = [refusal]
            with pytest.raises(AlotsError) as raised:
                client.upload_sample(b"x", "a.png", "image/png")
        self.assertIn("Invalid file type", str(raised.value))
