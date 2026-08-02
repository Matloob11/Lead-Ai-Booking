"""
Shared fixtures for the A7 WABA connector test suite (BE-06).

Every test runs against a throwaway SQLite file and with the Meta / Bitrix HTTP
clients replaced by recording fakes, so the suite never touches ALOTS.IO, Meta,
or a live Bitrix portal. Nothing here binds a port.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeMetaClient:
    """Records outbound Meta calls instead of performing them."""

    def __init__(self):
        self.text_messages = []
        self.media_messages = []
        self.template_messages = []
        self.templates_response = {
            "data": [
                {"name": "welcome_villa", "status": "APPROVED", "language": "en"},
            ]
        }

    def send_text_message(self, phone_number_id, to_phone, body):
        self.text_messages.append(
            {"phone_number_id": phone_number_id, "to": to_phone, "body": body}
        )
        return {"messages": [{"id": f"wamid.TEXT{len(self.text_messages)}"}]}

    def send_media_message(self, phone_number_id, to_phone, media_type, media_url,
                           caption=None, filename=None):
        self.media_messages.append({
            "phone_number_id": phone_number_id,
            "to": to_phone,
            "media_type": media_type,
            "media_url": media_url,
            "caption": caption,
            "filename": filename,
        })
        return {"messages": [{"id": f"wamid.MEDIA{len(self.media_messages)}"}]}

    def send_template_message(self, phone_number_id, to_phone, template_name,
                              language_code="en", components=None):
        self.template_messages.append({
            "phone_number_id": phone_number_id,
            "to": to_phone,
            "template_name": template_name,
            "language_code": language_code,
            "components": components or [],
        })
        return {"messages": [{"id": f"wamid.TMPL{len(self.template_messages)}"}]}

    def fetch_message_templates(self, waba_id=None):
        return self.templates_response


class FakeBitrixClient:
    """Records inbound deliveries into Bitrix Open Channels."""

    def __init__(self):
        self.inbound = []
        self.activations = []

    def send_inbound_message(self, line_id, client_phone, client_name, msg_id,
                             text, files=None, timestamp=None):
        self.inbound.append({
            "line_id": str(line_id),
            "client_phone": client_phone,
            "client_name": client_name,
            "msg_id": msg_id,
            "text": text,
            "files": files or [],
            "timestamp": timestamp,
        })
        return {"result": True}

    def activate_line(self, line_id, active=1):
        self.activations.append({"line_id": str(line_id), "active": active})
        return {"result": True}


@pytest.fixture
def connector(tmp_path, monkeypatch):
    """
    Imports the connector against an isolated DB and swaps in the fake clients.

    The module is reloaded per test so module-level `store` / client singletons
    never leak state between tests.
    """
    db_path = tmp_path / "waba_test.db"
    monkeypatch.setenv("A7_WABA_DB_PATH", str(db_path))
    monkeypatch.setenv("A7_WABA_LINE_MAPPINGS", "{}")
    monkeypatch.setenv("ALOTS_WEBHOOK_SECRET", "test-verify-token")

    import a7_waba_config
    import a7_waba_session
    import a7_waba_connector

    importlib.reload(a7_waba_config)
    importlib.reload(a7_waba_session)
    module = importlib.reload(a7_waba_connector)

    # Keep the json fallback used by set_line_mapping inside tmp_path too, so the
    # suite never writes to the real ./data directory.
    monkeypatch.setattr(a7_waba_config, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(module, "meta_client", FakeMetaClient())
    monkeypatch.setattr(module, "bitrix_client", FakeBitrixClient())

    return module


@pytest.fixture
def client(connector):
    from fastapi.testclient import TestClient

    with TestClient(connector.app) as test_client:
        yield test_client


@pytest.fixture
def store(connector):
    return connector.store


@pytest.fixture
def meta(connector):
    return connector.meta_client


@pytest.fixture
def bitrix(connector):
    return connector.bitrix_client


def inbound_payload(message, phone_number_id="1001234567", profile_name="Test Client"):
    """Wraps a single Meta message in the standard webhook entry/changes envelope."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": profile_name}}],
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }
