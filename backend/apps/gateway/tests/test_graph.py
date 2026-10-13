from unittest.mock import MagicMock, patch

import pytest
from django.test import SimpleTestCase, override_settings

from apps.gateway.client import AlotsError
from apps.gateway.graph import _APP_IDS, GraphNotConfigured, MetaGraphClient


def _response(status_code, body):
    response = MagicMock(status_code=status_code, content=b"{}", text="{}")
    response.json.return_value = body
    return response


class MetaGraphClientTests(SimpleTestCase):
    def setUp(self):
        _APP_IDS.clear()

    def test_missing_token_says_what_to_add(self):
        with override_settings(META_GRAPH_ACCESS_TOKEN=""):
            with pytest.raises(GraphNotConfigured) as raised:
                MetaGraphClient()
        self.assertIn("META_GRAPH_ACCESS_TOKEN", str(raised.value))
        self.assertEqual(raised.value.status_code, 503)

    @patch("apps.gateway.graph.ApiCall.save")
    def test_upload_sample_opens_a_session_then_sends_the_bytes(self, _save):
        with override_settings(META_GRAPH_ACCESS_TOKEN="tok", META_APP_ID="123"):
            client = MetaGraphClient()
            with patch("apps.gateway.graph.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.side_effect = [
                    _response(200, {"id": "upload:ABC?sig=S"}),
                    _response(200, {"h": "4::aW1hZ2UvanBlZw==:HANDLE"}),
                ]
                handle = client.upload_sample(b"\xff\xd8bytes", "villa.jpg", "image/jpeg")

        self.assertEqual(handle, "4::aW1hZ2UvanBlZw==:HANDLE")
        first, second = http.request.call_args_list

        self.assertEqual(first.args[:2], ("POST", "https://graph.facebook.com/v23.0/123/uploads"))
        self.assertEqual(
            first.kwargs["params"],
            {"file_length": 7, "file_type": "image/jpeg", "file_name": "villa.jpg"},
        )
        self.assertEqual(first.kwargs["headers"]["Authorization"], "Bearer tok")

        # The session id travels verbatim, signature and all, and this one
        # call is OAuth with the byte offset — Meta's own recipe.
        self.assertEqual(second.args[:2], ("POST", "https://graph.facebook.com/v23.0/upload:ABC?sig=S"))
        self.assertEqual(second.kwargs["content"], b"\xff\xd8bytes")
        self.assertEqual(second.kwargs["headers"]["Authorization"], "OAuth tok")
        self.assertEqual(second.kwargs["headers"]["file_offset"], "0")

    @patch("apps.gateway.graph.ApiCall.save")
    def test_app_id_is_asked_of_meta_once(self, _save):
        with override_settings(META_GRAPH_ACCESS_TOKEN="tok", META_APP_ID=""):
            with patch("apps.gateway.graph.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.return_value = _response(200, {"id": "9876"})
                self.assertEqual(MetaGraphClient().app_id(), "9876")
                self.assertEqual(MetaGraphClient().app_id(), "9876")

        self.assertEqual(http.request.call_count, 1)
        self.assertEqual(http.request.call_args.args[1], "https://graph.facebook.com/v23.0/app")

    def test_configured_app_id_wins(self):
        with override_settings(META_GRAPH_ACCESS_TOKEN="tok", META_APP_ID="555"):
            with patch("apps.gateway.graph.httpx.Client") as client_cls:
                self.assertEqual(MetaGraphClient().app_id(), "555")
        client_cls.assert_not_called()

    @patch("apps.gateway.graph.ApiCall.save")
    def test_meta_sentence_surfaces_on_failure(self, _save):
        with override_settings(META_GRAPH_ACCESS_TOKEN="tok"):
            client = MetaGraphClient()
            with patch("apps.gateway.graph.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.return_value = _response(
                    400,
                    {
                        "error": {
                            "message": "(#100) Invalid parameter",
                            "error_user_msg": "The header handle is not valid for this app",
                        }
                    },
                )
                with pytest.raises(AlotsError) as raised:
                    client.create_template("555", {"name": "brochure"})

        self.assertIn("header handle is not valid", str(raised.value))
        self.assertEqual(raised.value.status_code, 400)
        call = http.request.call_args
        self.assertEqual(call.args[:2], ("POST", "https://graph.facebook.com/v23.0/555/message_templates"))
        self.assertEqual(call.kwargs["json"], {"name": "brochure"})

    @patch("apps.gateway.graph.ApiCall.save")
    def test_logged_path_drops_the_upload_signature(self, save):
        with override_settings(META_GRAPH_ACCESS_TOKEN="tok"):
            client = MetaGraphClient()
            with patch("apps.gateway.graph.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.request.return_value = _response(200, {"h": "H"})
                with patch("apps.gateway.graph.ApiCall") as api_call:
                    client._call("POST", "/upload:ABC?sig=SECRET", content=b"x", log_body=False)

        record_kwargs = api_call.call_args.kwargs
        self.assertEqual(record_kwargs["path"], "[graph]/v23.0/upload:ABC")
        self.assertIsNone(record_kwargs["request_body"])
