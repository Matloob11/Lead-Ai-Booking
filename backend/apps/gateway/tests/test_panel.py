from unittest.mock import MagicMock, patch

import pytest
from django.test import SimpleTestCase, override_settings

from apps.gateway.client import AlotsError
from apps.gateway.panel import (
    AlotsPanelClient,
    PanelNotConfigured,
    PanelSessionExpired,
    cookie_header,
    merge_set_cookies,
    parse_cookie_header,
)


class _Headers(dict):
    """Enough of httpx.Headers for the client: get() and get_list()."""

    def __init__(self, single=None, set_cookies=None):
        super().__init__(single or {})
        self._set_cookies = list(set_cookies or [])

    def get_list(self, name):
        return self._set_cookies if name.lower() == "set-cookie" else []


def _response(status_code, body=None, text="", headers=None, set_cookies=None):
    response = MagicMock(status_code=status_code, text=text, headers=_Headers(headers, set_cookies))
    if body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


class CookieJarTests(SimpleTestCase):
    def test_parse_and_rebuild(self):
        jar = parse_cookie_header("a=1; b=2=x; a=9")
        self.assertEqual(jar, {"a": "1", "b": "2=x"})
        self.assertEqual(cookie_header(jar), "a=1; b=2=x")

    def test_renewed_auth_cookie_updates_value_and_expiry(self):
        jar = {"SmartBWAomniAuth": "old", "SmartBWAomniAuthC1": "c1", ".icpaas.session": "s"}
        renewed = merge_set_cookies(
            jar,
            [
                "SmartBWAomniAuth=new; expires=Tue, 22 Sep 2099 19:52:35 GMT; path=/; secure; httponly",
                "SmartBWAomniAuthC1=c1new; expires=Tue, 22 Sep 2099 19:52:35 GMT; path=/; httponly",
            ],
        )
        self.assertEqual(jar["SmartBWAomniAuth"], "new")
        self.assertEqual(jar["SmartBWAomniAuthC1"], "c1new")
        self.assertEqual(jar[".icpaas.session"], "s")
        self.assertEqual(renewed.year, 2099)

    def test_deleted_cookie_leaves_the_jar(self):
        jar = {"a": "1", "b": "2"}
        renewed = merge_set_cookies(jar, ["a=; max-age=0; path=/", "b=gone; expires=Thu, 01 Jan 1970 00:00:00 GMT"])
        self.assertEqual(jar, {})
        self.assertIsNone(renewed)


class PanelClientTests(SimpleTestCase):
    def test_no_cookie_says_what_to_add(self):
        with pytest.raises(PanelNotConfigured) as raised:
            AlotsPanelClient(cookie="")
        self.assertIn("ALOTS_UI_COOKIE_B64", str(raised.value))

    @patch("apps.gateway.panel.ApiCall.save")
    def test_upload_returns_the_handle_and_logs_without_it(self, _save):
        with override_settings(ALOTS_BASE_URL="https://alots.io"):
            with patch("apps.gateway.panel.httpx.Client") as client_cls:
                http = client_cls.return_value.__enter__.return_value
                http.post.return_value = _response(
                    200,
                    {"status": True, "message": "Media uploaded successfully.", "url": "https://x/y.png", "hValue": "4:abc:def"},
                    set_cookies=["c=renewed; path=/"],
                )
                with patch("apps.gateway.panel.ApiCall") as api_call:
                    client = AlotsPanelClient(cookie="a=b; c=d")
                    handle = client.upload_template_sample(b"\x89PNG", "y.png", "image/png", "IMAGE", "555")

        self.assertEqual(handle, "4:abc:def")
        # A renewed cookie is kept for the next call.
        self.assertEqual(client.cookie, "a=b; c=renewed")
        call = http.post.call_args
        self.assertEqual(call.args[0], "https://alots.io/WAMessage/WATemplate/UploadMedia")
        self.assertEqual(call.kwargs["headers"]["Cookie"], "a=b; c=d")
        self.assertEqual(call.kwargs["data"], {"fileType": "Image", "originalFileName": "y.png", "WABABusinessId": "555"})
        self.assertEqual(call.kwargs["files"]["mediaFile"][0], "y.png")
        record = api_call.return_value
        self.assertEqual(record.response_body["hValue"], True)
        self.assertNotIn("4:abc:def", str(record.response_body))

    @patch("apps.gateway.panel.ApiCall.save")
    def test_redirect_to_signin_means_the_session_expired(self, _save):
        with patch("apps.gateway.panel.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.post.return_value = _response(302, headers={"location": "/signin?ReturnUrl=%2F"})
            with pytest.raises(PanelSessionExpired) as raised:
                AlotsPanelClient(cookie="a=b").upload_template_sample(b"x", "y.png", "image/png", "IMAGE", "555")
        self.assertIn("set-alots-ui-cookie", str(raised.value))
        self.assertEqual(raised.value.status_code, 503)

    @patch("apps.gateway.panel.ApiCall.save")
    def test_html_instead_of_json_also_means_expired(self, _save):
        with patch("apps.gateway.panel.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.post.return_value = _response(200, text="<!DOCTYPE html>")
            with pytest.raises(PanelSessionExpired):
                AlotsPanelClient(cookie="a=b").upload_template_sample(b"x", "y.png", "image/png", "IMAGE", "555")

    @patch("apps.gateway.panel.ApiCall.save")
    def test_panel_refusal_surfaces_its_message(self, _save):
        with patch("apps.gateway.panel.httpx.Client") as client_cls:
            http = client_cls.return_value.__enter__.return_value
            http.post.return_value = _response(200, {"status": False, "message": "Image size must be less than 5 MB."})
            with pytest.raises(AlotsError) as raised:
                AlotsPanelClient(cookie="a=b").upload_template_sample(b"x", "y.png", "image/png", "IMAGE", "555")
        self.assertIn("less than 5 MB", str(raised.value))

    def test_unknown_kind_is_refused_before_any_call(self):
        with patch("apps.gateway.panel.httpx.Client") as client_cls:
            with pytest.raises(AlotsError):
                AlotsPanelClient(cookie="a=b").upload_template_sample(b"x", "y.png", "audio/ogg", "AUDIO", "555")
        client_cls.assert_not_called()
