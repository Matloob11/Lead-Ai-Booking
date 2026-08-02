# Local Development & Testing Guide

This guide details how to run, test, and verify the A7 WhatsApp Business API Connector locally without touching AWS or live Bitrix production servers.

---

## 1. Prerequisites & Environment Setup

- Python 3.10+
- Virtual environment created locally

### Install Dependencies:
```bash
pip install fastapi uvicorn pydantic requests pytest
```

---

## 2. Running the Local Backend Connector

Run Uvicorn from the project root directory:

```bash
python -m uvicorn a7_waba_connector:app --reload --port 8088
```

The service will start locally at `http://127.0.0.1:8088`.

### Key Local Endpoints:
- **Health Check**: `GET http://127.0.0.1:8088/api/v1/health`
- **Inbound Webhook**: `POST http://127.0.0.1:8088/api/v1/meta/webhook`
- **Bitrix Outbound Hook**: `POST http://127.0.0.1:8088/api/v1/bitrix/outbound`
- **Template Proxy**: `GET http://127.0.0.1:8088/api/v1/templates`
- **Template Outbound**: `POST http://127.0.0.1:8088/api/v1/templates/send`
- **Line Mappings**: `GET / POST http://127.0.0.1:8088/api/v1/lines`

---

## 3. Testing Local Webhooks with Curl

### A. Simulate Inbound WhatsApp Client Message:
```bash
curl -X POST "http://127.0.0.1:8088/api/v1/meta/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [
      {
        "changes": [
          {
            "value": {
              "messaging_product": "whatsapp",
              "metadata": {"phone_number_id": "1001234567"},
              "contacts": [{"profile": {"name": "Test Client"}}],
              "messages": [
                {
                  "from": "923001234567",
                  "id": "wamid_test_001",
                  "timestamp": 1722580000,
                  "type": "text",
                  "text": {"body": "Hello, interested in 3-bedroom villa!"}
                }
              ]
            }
          }
        ]
      }
    ]
  }'
```

### B. Simulate Bitrix Agent Outbound Reply:
```bash
curl -X POST "http://127.0.0.1:8088/api/v1/bitrix/outbound" \
  -H "Content-Type: application/json" \
  -d '{
    "LINE": "1",
    "MESSAGES": [
      {
        "user": {"phone": "923001234567"},
        "message": {"id": "out_001", "text": "Sure! Here are the details."}
      }
    ]
  }'
```

---

## 4. Local Widget Preview

Open `a7_waba_widget.html` directly in your browser or serve it via a local static web server to test template selection, dynamic variable rendering, and message submission against `http://127.0.0.1:8088`.
