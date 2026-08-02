"""
A7 Bitrix24 WhatsApp Business API (Omni Channel) FastAPI Middleware
Handles Meta WABA / ALOTS.IO Webhooks, Bitrix imconnector integration, 24-hour window enforcement,
and Outbound Meta Approved Template Sender API.
"""

import time
import json
import datetime
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request, Query, Response, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from a7_waba_config import (
    ALOTS_WEBHOOK_SECRET, ALOTS_WABA_ID, CONNECTOR_ID,
    SESSION_WINDOW_HOURS, get_config_summary
)
from a7_waba_session import WABAStore
from a7_waba_meta_client import MetaWABAClient
from a7_waba_bitrix_client import BitrixConnectorClient

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("a7_waba_connector")

# Initialize FastAPI App
app = FastAPI(
    title="A7 Bitrix24 WhatsApp Business API Connector",
    version="1.0.0",
    description="Custom In-House Omni Channel Connector bridging Meta WABA / ALOTS.IO with Bitrix24 Open Channels"
)

# Enable CORS for Bitrix Widget embedding
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Instances
store = WABAStore()
meta_client = MetaWABAClient()
bitrix_client = BitrixConnectorClient()


# --- Pydantic Data Models ---

class LineMappingRequest(BaseModel):
    phone_number_id: str = Field(..., description="Meta WhatsApp Phone Number ID or WABA Number")
    line_id: str = Field(..., description="Bitrix Open Line ID (1-50)")
    label: Optional[str] = Field("", description="Agent Name or Line Description")


class TemplateSendRequest(BaseModel):
    client_phone: str = Field(..., description="Recipient Client Phone Number with country code")
    phone_number_id: str = Field(..., description="Sender WhatsApp Phone Number ID")
    template_name: str = Field(..., description="Approved Meta Template Name")
    language_code: str = Field("en", description="Template Language Code")
    components: Optional[List[Dict[str, Any]]] = Field(default=[], description="Header/Body/Button parameters")


# --- Health & Status Endpoints ---

@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    cfg = get_config_summary()
    lines = store.list_line_mappings()
    return {
        "status": "online",
        "timestamp": int(time.time()),
        "config": cfg,
        "active_line_mappings_count": len(lines),
        "lines": lines
    }


@app.get("/api/v1/session/status")
def session_status(client_phone: str = Query(..., description="Client phone number, with or without '+'")):
    """
    Returns the 24-hour Meta session window state for a client phone.

    Consumed by the Bitrix side-panel widget countdown timer. `server_time` is
    included so the widget can correct for agent-machine clock skew instead of
    trusting its own clock against `expires_at`.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    normalized_phone = str(client_phone).strip().lstrip("+")

    payload: Dict[str, Any] = {
        "status": "success",
        "client_phone": normalized_phone,
        "session_window_hours": SESSION_WINDOW_HOURS,
        "server_time": now.isoformat(),
        "window_active": False,
        "remaining_seconds": 0,
        "expires_at": None,
        "last_client_msg_ts": None,
        "line_id": None,
        "phone_number_id": None,
    }

    session = store.get_client_session(normalized_phone)
    if not session:
        # Client has never messaged in: template-only mode, no window to count down.
        payload["reason"] = "no_inbound_message"
        return payload

    last_ts = session["last_client_msg_ts"]
    expires_at = last_ts + datetime.timedelta(hours=SESSION_WINDOW_HOURS)
    remaining_seconds = int((expires_at - now).total_seconds())

    payload.update({
        "window_active": remaining_seconds > 0,
        "remaining_seconds": max(remaining_seconds, 0),
        "expires_at": expires_at.isoformat(),
        "last_client_msg_ts": last_ts.isoformat(),
        "line_id": session.get("line_id"),
        "phone_number_id": session.get("phone_number_id"),
    })
    if remaining_seconds <= 0:
        payload["reason"] = "window_expired"
    return payload


# --- Webhook Endpoint for ALOTS.IO / Meta WABA ---

@app.get("/api/v1/meta/webhook")
def verify_meta_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """Meta Webhook Challenge Verification."""
    if hub_mode == "subscribe" and hub_challenge:
        if ALOTS_WEBHOOK_SECRET and hub_verify_token != ALOTS_WEBHOOK_SECRET:
            logger.warning("Webhook verification token mismatch!")
            raise HTTPException(status_code=403, detail="Verification token mismatch")
        logger.info("Webhook verification succeeded.")
        return Response(content=hub_challenge, media_type="text/plain")
    return {"status": "A7 WABA Webhook Receiver Active"}


@app.post("/api/v1/meta/webhook")
async def process_meta_webhook(request: Request):
    """
    Receives incoming WhatsApp messages & statuses from Meta WABA / ALOTS.IO.
    Extracts message details, updates 24h session window, maps to Bitrix Open Line, and sends to Bitrix.
    """
    try:
        body = await request.json()
    except Exception as err:
        logger.error(f"Failed to parse webhook JSON body: {err}")
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)

    logger.debug(f"Received Meta Webhook Payload: {json.dumps(body)}")

    # Parse standard Meta Cloud API entry format
    entries = body.get("entry", [])
    if not entries:
        # Check direct fallback format
        if "messages" in body:
            entries = [{"changes": [{"value": body}]}]

    processed_count = 0
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id") or value.get("phone_number_id", "default")
            
            # Map phone_number_id to Bitrix Open Line ID (1-50)
            line_id = store.get_line_id(phone_number_id)

            # Process inbound messages
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            profile_name = ""
            if contacts:
                profile_name = contacts[0].get("profile", {}).get("name", "")

            for msg in messages:
                msg_id = msg.get("id", f"wamid_{int(time.time()*1000)}")
                from_phone = msg.get("from", "")
                msg_type = msg.get("type", "text")
                timestamp = int(msg.get("timestamp", time.time()))

                if not from_phone:
                    continue

                # 1. Touch 24-Hour Session Window in DB
                store.touch_client_session(from_phone, phone_number_id, line_id)

                # 2. Extract Message Content & Media Files
                text_content = ""
                files = []

                if msg_type == "text":
                    text_content = msg.get("text", {}).get("body", "")
                elif msg_type == "image":
                    img_info = msg.get("image", {})
                    caption = img_info.get("caption", "")
                    text_content = f"[Image] {caption}".strip()
                    if img_info.get("link"):
                        files.append({"url": img_info["link"], "name": "image.jpg"})
                elif msg_type == "document":
                    doc_info = msg.get("document", {})
                    caption = doc_info.get("caption", "")
                    filename = doc_info.get("filename", "document.pdf")
                    text_content = f"[Document: {filename}] {caption}".strip()
                    if doc_info.get("link"):
                        files.append({"url": doc_info["link"], "name": filename})
                elif msg_type in ("audio", "voice"):
                    audio_info = msg.get(msg_type, {})
                    text_content = f"[{msg_type.capitalize()} Message]"
                    if audio_info.get("link"):
                        files.append({"url": audio_info["link"], "name": f"{msg_type}.mp3"})
                elif msg_type == "video":
                    vid_info = msg.get("video", {})
                    caption = vid_info.get("caption", "")
                    text_content = f"[Video] {caption}".strip()
                    if vid_info.get("link"):
                        files.append({"url": vid_info["link"], "name": "video.mp4"})
                elif msg_type == "location":
                    loc = msg.get("location", {})
                    lat, lng = loc.get("latitude"), loc.get("longitude")
                    text_content = f"📍 Location Shared: https://maps.google.com/?q={lat},{lng} ({loc.get('name', '')})"
                elif msg_type == "button" or msg_type == "interactive":
                    btn_text = msg.get("button", {}).get("text") or msg.get("interactive", {}).get("button_reply", {}).get("title", "")
                    text_content = f"[Button Selected]: {btn_text}"
                else:
                    text_content = f"[{msg_type.upper()} Message Received]"

                # 3. Log Inbound Message
                store.log_message(msg_id, from_phone, phone_number_id, line_id, "inbound", msg_type, text_content, "received")

                # 4. Deliver into Bitrix Open Channels Chat
                res = bitrix_client.send_inbound_message(
                    line_id=line_id,
                    client_phone=from_phone,
                    client_name=profile_name or f"+{from_phone}",
                    msg_id=msg_id,
                    text=text_content,
                    files=files,
                    timestamp=timestamp
                )
                logger.info(f"Delivered message to Bitrix (Line {line_id}, Phone {from_phone}): {res}")
                processed_count += 1

    return {"status": "success", "processed_messages": processed_count}


# --- Webhook Endpoint for Bitrix24 Outbound Messages ---

@app.post("/api/v1/bitrix/outbound")
async def process_bitrix_outbound(request: Request):
    """
    Handles ONIMCONNECTORMESSAGEADD event sent by Bitrix24 when an agent replies in Chat UI.
    Verifies 24-hour window:
    - Active (<24h): Sends freeform message to Meta WhatsApp API.
    - Expired (>24h): Rejects message and notifies agent to send Meta Approved Template.
    """
    try:
        data = await request.json()
    except Exception:
        form_data = await request.form()
        data = dict(form_data)

    logger.info(f"Received Bitrix Outbound Message Event: {json.dumps(data)}")

    # Extract Bitrix Event Details
    event_data = data.get("data", {}) or data
    messages = event_data.get("MESSAGES", []) or event_data.get("messages", [])
    
    if not messages and "message" in event_data:
        messages = [event_data]

    sent_results = []
    for item in messages:
        msg_obj = item.get("message", {})
        user_obj = item.get("user", {})
        chat_obj = item.get("chat", {})

        client_phone = user_obj.get("phone") or chat_obj.get("id", "").replace("wa_chat_", "").replace("wa_", "")
        line_id = event_data.get("LINE") or data.get("LINE") or "1"
        text_body = msg_obj.get("text", "").strip()
        msg_id = msg_obj.get("id", f"out_{int(time.time()*1000)}")

        if not client_phone:
            logger.warning("Bitrix outbound event missing client phone number!")
            continue

        # Reverse lookup phone_number_id for this line_id
        phone_number_id = "default"
        mappings = store.list_line_mappings()
        for m in mappings:
            if str(m.get("line_id")) == str(line_id):
                phone_number_id = m.get("phone_number_id")
                break

        # 1. Enforce 24-Hour Session Window Check
        is_active, remaining_hours = store.is_24h_window_active(client_phone)
        if not is_active:
            logger.warning(f"24-Hour Session Window EXPIRED for {client_phone}! Cannot send freeform text.")
            
            # Send warning back into Bitrix chat so agent is informed
            bitrix_client.send_inbound_message(
                line_id=line_id,
                client_phone=client_phone,
                client_name="System Warning",
                msg_id=f"warn_{int(time.time()*1000)}",
                text="⚠️ 24-Hour Session Window Expired! Client must receive a Meta Approved Template message to reopen the chat. Please use the Template Sender Widget in CRM."
            )
            sent_results.append({"status": "blocked_24h_expired", "client_phone": client_phone})
            continue

        # 2. Handle Attachments if present
        files = msg_obj.get("files", [])
        if files:
            for f in files:
                file_url = f.get("url") or f.get("link")
                file_name = f.get("name", "file")
                res = meta_client.send_media_message(phone_number_id, client_phone, "document", file_url, caption=text_body, filename=file_name)
                store.log_message(msg_id, client_phone, phone_number_id, line_id, "outbound", "media", file_url)
                sent_results.append(res)
        elif text_body:
            # 3. Send Freeform Text Message
            res = meta_client.send_text_message(phone_number_id, client_phone, text_body)
            store.log_message(msg_id, client_phone, phone_number_id, line_id, "outbound", "text", text_body)
            sent_results.append(res)

    return {"status": "processed", "results": sent_results}


# --- Approved Meta Templates & Outbound Sender Endpoints ---

@app.get("/api/v1/templates")
def get_approved_templates(waba_id: Optional[str] = None):
    """Fetches list of approved Meta templates for WABA account."""
    templates = meta_client.fetch_message_templates(waba_id=waba_id)
    return templates


@app.post("/api/v1/templates/send")
def send_approved_template(req: TemplateSendRequest):
    """
    Sends a Meta Approved Template message to client.
    Initializes/Touches client session window so that client reply re-opens 24h chat.
    """
    line_id = store.get_line_id(req.phone_number_id)

    # Dispatch template via ALOTS.IO Meta API
    res = meta_client.send_template_message(
        phone_number_id=req.phone_number_id,
        to_phone=req.client_phone,
        template_name=req.template_name,
        language_code=req.language_code,
        components=req.components
    )

    # Touch session store & log message
    store.touch_client_session(req.client_phone, req.phone_number_id, line_id)
    store.log_message(
        msg_id=res.get("messages", [{}])[0].get("id", f"tmpl_{int(time.time()*1000)}"),
        client_phone=req.client_phone,
        phone_number_id=req.phone_number_id,
        line_id=line_id,
        direction="outbound",
        msg_type="template",
        content=f"Template Sent: {req.template_name}",
        status="sent"
    )

    return {"status": "success", "meta_response": res, "line_id": line_id}


# --- Line & Number Mapping Endpoints (Support for 50 Agents) ---

@app.get("/api/v1/lines")
def list_lines():
    """Lists all configured Phone Number to Bitrix Open Line mappings."""
    return {"status": "success", "lines": store.list_line_mappings()}


@app.post("/api/v1/lines")
def set_line(req: LineMappingRequest):
    """
    Registers or updates phone number ID to Bitrix Open Line mapping (50 Agents).
    Also calls Bitrix imconnector.activate for that line.
    """
    store.set_line_mapping(req.phone_number_id, req.line_id, req.label or "")
    bitrix_res = bitrix_client.activate_line(req.line_id, active=1)
    return {
        "status": "success",
        "phone_number_id": req.phone_number_id,
        "line_id": req.line_id,
        "bitrix_activation": bitrix_res
    }
