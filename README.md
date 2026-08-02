# A7 Bitrix24 WhatsApp Business API (WABA) Integration System

## Master Documentation Suite

Welcome to the **A7 WABA Integration Hub** repository. This project provides a direct, in-house integration between **Meta Cloud WhatsApp Business API** and **Bitrix24 Open Channels** for 50+ sales agents, featuring 24-hour session window tracking, Meta HSM approved template messaging, and dedicated phone number routing.

---

## 📚 Complete Project Documentation Index

1. 📘 **[01 - System Overview & Business Vision](file:///C:/Users/Matloob/Desktop/a7-full-whatsapp-system/docs/01_SYSTEM_OVERVIEW.md)**
   - Business Purpose, Zero Third-Party Subscription Model, Architectural Pillars.
2. 📗 **[02 - Bitrix24 Open Channels Connector Specification](file:///C:/Users/Matloob/Desktop/a7-full-whatsapp-system/docs/02_BITRIX24_OPEN_CHANNELS_CONNECTOR.md)**
   - Local App Scopes, `imconnector` REST API methods, Inbound & Outbound workflows.
3. 📙 **[03 - Meta WhatsApp Business API Cloud Specification](file:///C:/Users/Matloob/Desktop/a7-full-whatsapp-system/docs/03_META_WABA_API_SPECIFICATION.md)**
   - Webhook Verification, HMAC SHA-256 Signature Security, `/messages` API payloads.
4. 📕 **[04 - 24-Hour Session Window & Template Engine](file:///C:/Users/Matloob/Desktop/a7-full-whatsapp-system/docs/04_SESSION_WINDOW_AND_TEMPLATES.md)**
   - WhatsApp 24h Window Policy, Meta Approved HSM Templates, Embedded UI Widget.
5. 📓 **[05 - Local Development & Testing Guide](file:///C:/Users/Matloob/Desktop/a7-full-whatsapp-system/docs/05_LOCAL_DEVELOPMENT_AND_TESTING_GUIDE.md)**
   - Running Local Django Server, Local Admin Panel (`http://127.0.0.1:8000/admin/`), Mock Payload Testing.

---

## 🛠️ Quick Local Setup
```bash
cd C:\Users\Matloob\Desktop\a7-full-whatsapp-system
python manage.py migrate
python manage.py runserver 8000
```
- **Admin Dashboard**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)
- **Superuser Email**: `admin@example.com`
- **Superuser Password**: `admin123456`