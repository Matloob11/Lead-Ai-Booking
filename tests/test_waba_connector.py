"""
Comprehensive Unit & Integration Test Suite for A7 WhatsApp Business API Connector
Tests FastAPI endpoints, 24-hour session window math, multi-agent line routing,
and outbound template dispatching locally.
"""

import time
import datetime
import pytest
from fastapi.testclient import TestClient

from a7_waba_connector import app, store

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "config" in data
    assert "active_line_mappings_count" in data


def test_line_mapping_store():
    # Test setting and getting line mapping for 50 agents
    store.set_line_mapping("100998877", "15", "Agent 15 Line")
    line_id = store.get_line_id("100998877")
    assert line_id == "15"

    lines = store.list_line_mappings()
    assert any(l["phone_number_id"] == "100998877" and l["line_id"] == "15" for l in lines)


def test_24h_session_window_logic():
    test_phone = "923009998877"
    
    # 1. Touch session for client (Active session)
    store.touch_client_session(test_phone, "100998877", "15")
    is_active, remaining_hours = store.is_24h_window_active(test_phone)
    assert is_active is True
    assert remaining_hours > 23.0

    # 2. Simulate expired session (> 24 hours ago)
    past_time_str = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).isoformat()
    with store._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE client_sessions SET last_client_msg_ts = ? WHERE client_phone = ?", (past_time_str, test_phone))
        conn.commit()

    is_active_expired, rem_expired = store.is_24h_window_active(test_phone)
    assert is_active_expired is False
    assert rem_expired == 0.0


def test_meta_webhook_inbound_processing():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "100998877"},
                            "contacts": [{"profile": {"name": "Test Lead"}}],
                            "messages": [
                                {
                                    "from": "923001112233",
                                    "id": "wamid_unittest_001",
                                    "timestamp": int(time.time()),
                                    "type": "text",
                                    "text": {"body": "Hello, need details about villa!"}
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    response = client.post("/api/v1/meta/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["processed_messages"] == 1

    # Verify session was touched and is active
    is_active, rem = store.is_24h_window_active("923001112233")
    assert is_active is True


def test_bitrix_outbound_active_vs_expired_24h():
    active_phone = "923001112233"
    expired_phone = "923004445566"

    # Make active_phone session active
    store.touch_client_session(active_phone, "100998877", "15")

    # Make expired_phone session expired
    past_time_str = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).isoformat()
    with store._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO client_sessions (client_phone, phone_number_id, line_id, last_client_msg_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_phone) DO UPDATE SET last_client_msg_ts = excluded.last_client_msg_ts
        """, (expired_phone, "100998877", "15", past_time_str))
        conn.commit()

    # 1. Outbound to active phone (Should succeed)
    outbound_active_payload = {
        "LINE": "15",
        "MESSAGES": [
            {
                "user": {"phone": active_phone},
                "message": {"id": "out_001", "text": "Here are the villa details!"}
            }
        ]
    }
    resp1 = client.post("/api/v1/bitrix/outbound", json=outbound_active_payload)
    assert resp1.status_code == 200

    # 2. Outbound to expired phone (Should be blocked by 24h rule)
    outbound_expired_payload = {
        "LINE": "15",
        "MESSAGES": [
            {
                "user": {"phone": expired_phone},
                "message": {"id": "out_002", "text": "Following up..."}
            }
        ]
    }
    resp2 = client.post("/api/v1/bitrix/outbound", json=outbound_expired_payload)
    assert resp2.status_code == 200
    res2_data = resp2.json()
    assert any(r.get("status") == "blocked_24h_expired" for r in res2_data.get("results", []))


def test_template_send_and_session_reopen():
    phone = "923008889900"
    payload = {
        "client_phone": phone,
        "phone_number_id": "100998877",
        "template_name": "welcome_offer",
        "language_code": "en",
        "components": []
    }

    response = client.post("/api/v1/templates/send", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify sending template reopens the 24-hour window
    is_active, _ = store.is_24h_window_active(phone)
    assert is_active is True
