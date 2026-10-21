"""POST /api/leadai/inventory/bitrix/ (bitrix_views.inventory_event; round 20): Bitrix's Availability webhook (Cursor's
C46 handler, a7_inventory_webhook.php) says a card was added or changed. Signed "leadai-inventory." + ts + "." + body
with CRM_LEAD_WA_SECRET in X-A7-Signature, the stamp in X-A7-Ts and in the body: 405 for any other method, 401 for a
missing, wrong or old signature, 400 for a body off the contract, else 200 and the card is read again in a task, once
per half minute per card."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from apps.leadai.tests.test_assistant import TEST_SETTINGS

URL = "/api/leadai/inventory/bitrix/"
SECRET = TEST_SETTINGS["CRM_LEAD_WA_SECRET"]


def signed(body, *, secret=SECRET, ts=None, prefix=b"leadai-inventory.", header_ts=True):
    raw = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
    ts = str(int(time.time()) if ts is None else ts)
    sign = hmac.new(secret.encode(), prefix + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    headers = {"HTTP_X_A7_SIGNATURE": sign}
    if header_ts:
        headers["HTTP_X_A7_TS"] = ts
    return raw, headers


@override_settings(**TEST_SETTINGS)
class InventoryWebhookTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.http = Client(enforce_csrf_checks=True)  # no session, no CSRF token: the signature is the key
        patcher = patch("apps.leadai.tasks.refresh_bitrix_unit.delay")
        self.delay = patcher.start()
        self.addCleanup(patcher.stop)
        # Nothing here may reach Bitrix: the card is read in the task, not in the request.
        patcher = patch("apps.crmlink.client.call", side_effect=AssertionError("read Bitrix in the request"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, body, **options):
        raw, headers = signed(body, **options)
        return self.http.post(URL, data=raw, content_type="application/json", **headers)

    @staticmethod
    def body(card=103048, ts=None):
        return {"event": "update", "id": card, "stageId": "DT1042_14:PREPARATION", "ts": int(time.time()) if ts is None else ts}

    def test_the_contract(self):
        self.assertEqual(self.http.get(URL).status_code, 405)
        raw = json.dumps(self.body()).encode()
        self.assertEqual(self.http.post(URL, data=raw, content_type="application/json").status_code, 401)  # unsigned
        for options in ({"secret": "another"}, {"ts": int(time.time()) - 301}, {"ts": int(time.time()) + 301}, {"prefix": b"leadai-botstatus."}, {"prefix": b"leadai-notify."}):
            with self.subTest(options=options):
                self.assertEqual(self.post(self.body(), **options).status_code, 401)
        self.delay.assert_not_called()
        response = self.post(self.body())
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True, "queued": True, "id": 103048}))
        self.delay.assert_called_once_with(103048)
        # The same hex in any case; a body changed after signing is refused.
        raw, headers = signed(self.body(card=103050))
        headers["HTTP_X_A7_SIGNATURE"] = headers["HTTP_X_A7_SIGNATURE"].upper()
        self.assertEqual(self.http.post(URL, data=raw, content_type="application/json", **headers).status_code, 200)
        self.assertEqual(self.http.post(URL, data=raw + b" ", content_type="application/json", **headers).status_code, 401)
        # The stamp in the body alone (no X-A7-Ts header) still signs; an old one in the body alone is old.
        ts = int(time.time())
        self.assertEqual(self.post(self.body(card=103051, ts=ts), ts=ts, header_ts=False).status_code, 200)
        self.assertEqual(self.post(self.body(card=103052, ts=ts - 400), ts=ts - 400, header_ts=False).status_code, 401)
        self.assertEqual(self.delay.call_count, 3)

    def test_a_body_off_the_contract_is_400(self):
        for body in (b"not json", b"[1, 2]", {"event": "update"}, {"event": "update", "id": "x"}, {"event": "update", "id": 0}, {"event": "update", "id": -5}, {"event": "update", "id": True}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)
        self.assertEqual(self.http.post(URL, data=b"{" * 20000, content_type="application/json").status_code, 400)
        self.delay.assert_not_called()
        # A card id as digits is a card.
        self.assertEqual(self.post({"event": "add", "id": "103049", "stageId": "", "ts": int(time.time())}).status_code, 200)
        self.delay.assert_called_once_with(103049)

    def test_a_nested_body_is_refused_not_a_500(self):
        # Unsigned and with no stamp header, a deeply nested document is never parsed: 401. Signed, it is 400.
        deep = b"[" * 16000
        self.assertEqual(self.http.post(URL, data=deep, content_type="application/json").status_code, 401)
        self.assertEqual(self.post(deep).status_code, 400)
        ts = int(time.time())
        stamped = b'{"ts":' + str(ts).encode() + b',"id":[' + b"[" * 15000
        self.assertEqual(self.post(stamped, ts=ts, header_ts=False).status_code, 400)
        self.delay.assert_not_called()

    def test_one_read_per_card_per_half_minute(self):
        self.assertEqual(self.post(self.body()).json(), {"ok": True, "queued": True, "id": 103048})
        self.assertEqual(self.post(self.body()).json(), {"ok": True, "queued": False, "id": 103048})
        self.assertEqual(self.post(self.body(card=103049)).json(), {"ok": True, "queued": True, "id": 103049})
        self.assertEqual(self.delay.call_count, 2)
        cache.clear()
        self.assertEqual(self.post(self.body()).json()["queued"], True)

    def test_no_secret_configured_is_401(self):
        with override_settings(CRM_LEAD_WA_SECRET=""):
            self.assertEqual(self.post(self.body(), secret="").status_code, 401)
        self.delay.assert_not_called()
