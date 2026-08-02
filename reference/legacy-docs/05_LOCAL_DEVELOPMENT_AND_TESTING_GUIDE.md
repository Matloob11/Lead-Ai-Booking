# 05 - Local Development & Testing Guide

## 1. Local Environment Requirements
- **Directory**: `C:\Users\Matloob\Desktop\a7-full-whatsapp-system`
- **Python Version**: Python 3.10+
- **Database**: Local SQLite (`db.sqlite3`)
- **Server Command**: `python manage.py runserver 8000`
- **Admin Dashboard**: `http://127.0.0.1:8000/admin/`
- **Admin Credentials**: `admin@example.com` / `admin123456`

---

## 2. Running Local Dev Server
```bash
cd C:\Users\Matloob\Desktop\a7-full-whatsapp-system
python manage.py migrate
python manage.py runserver 8000
```

---

## 3. Mock Webhook Testing Suite
You can simulate Meta incoming customer webhooks locally using `curl` or Postman:

### Inbound Message Mock Payload:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/waba/webhook/ \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "WABA_ACCOUNT_ID",
      "changes": [{
        "value": {
          "messaging_product": "whatsapp",
          "metadata": {
            "display_phone_number": "971500000000",
            "phone_number_id": "PHONE_ID_101"
          },
          "contacts": [{"wa_id": "971501234567", "profile": {"name": "Test Client"}}],
          "messages": [{
            "from": "971501234567",
            "id": "wamid.HBgLOTcxNTAxMjM0NTY3FQIAERgSQTUwRjEzM0Q0NzA0",
            "timestamp": "1785658433",
            "type": "text",
            "text": {"body": "Hello, I am interested in buying property."}
          }]
        },
        "field": "messages"
      }]
    }]
  }'
```

---

## 4. UI Widget Local Preview
To test the embedded agent panel locally:
1. Open `C:\Users\Matloob\Desktop\a7-full-whatsapp-system\a7_waba_widget.html` in your web browser.
2. Select a template from the dropdown.
3. Fill dynamic variables `{{1}}`, `{{2}}`.
4. Click **Send Template Message** and verify JSON payload output in browser developer tools console.
