"""
ALOTS.IO / Meta WABA Cloud API v23.0 Client
Handles sending freeform messages, media, and templates, as well as fetching templates.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional
from a7_waba_config import ALOTS_BASE_URL, ALOTS_API_KEY, ALOTS_VERSION, ALOTS_WABA_ID

logger = logging.getLogger("a7_waba_meta_client")


class MetaWABAClient:
    def __init__(self, api_key: str = ALOTS_API_KEY, base_url: str = ALOTS_BASE_URL, version: str = ALOTS_VERSION):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.version = version

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/{self.version}/{endpoint.lstrip('/')}"
        data_bytes = json.dumps(payload).encode("utf-8")
        headers = self._get_headers()
        
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                res_data = resp.read().decode("utf-8")
                return json.loads(res_data) if res_data else {"success": True}
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8") if err.fp else ""
            logger.error(f"HTTPError calling {url}: status={err.code}, body={err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"error": {"message": f"HTTP {err.code}: {err_body}", "code": err.code}}
        except Exception as err:
            logger.error(f"Error calling {url}: {err}")
            return {"error": {"message": str(err)}}

    def _get(self, endpoint: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{self.version}/{endpoint.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(params)
            url += f"?{query}"

        headers = self._get_headers()
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                res_data = resp.read().decode("utf-8")
                return json.loads(res_data) if res_data else {}
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8") if err.fp else ""
            logger.error(f"HTTPError GET {url}: status={err.code}, body={err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"error": {"message": f"HTTP {err.code}: {err_body}"}}
        except Exception as err:
            logger.error(f"Error GET {url}: {err}")
            return {"error": {"message": str(err)}}

    def send_text_message(self, phone_number_id: str, to_phone: str, body: str) -> Dict[str, Any]:
        """Sends freeform text message to customer."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "text",
            "text": {
                "preview_url": True,
                "body": body
            }
        }
        return self._post(f"{phone_number_id}/messages", payload)

    def send_media_message(self, phone_number_id: str, to_phone: str, media_type: str,
                           media_url: str, caption: Optional[str] = None, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends media message (image, document, audio, video).
        media_type must be one of: 'image', 'document', 'audio', 'video', 'sticker'
        """
        media_payload: Dict[str, Any] = {"link": media_url}
        if caption and media_type in ("image", "document", "video"):
            media_payload["caption"] = caption
        if filename and media_type == "document":
            media_payload["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": media_type,
            media_type: media_payload
        }
        return self._post(f"{phone_number_id}/messages", payload)

    def send_location_message(self, phone_number_id: str, to_phone: str,
                              latitude: float, longitude: float, name: str = "", address: str = "") -> Dict[str, Any]:
        """Sends location message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "location",
            "location": {
                "latitude": str(latitude),
                "longitude": str(longitude),
                "name": name,
                "address": address
            }
        }
        return self._post(f"{phone_number_id}/messages", payload)

    def send_template_message(self, phone_number_id: str, to_phone: str, template_name: str,
                              language_code: str = "en", components: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Sends Meta approved template message.
        components format:
        [
          {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": "https://..."}}]
          },
          {
            "type": "body",
            "parameters": [{"type": "text", "text": "Val 1"}, {"type": "text", "text": "Val 2"}]
          }
        ]
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                },
                "components": components or []
            }
        }
        return self._post(f"{phone_number_id}/messages", payload)

    def fetch_message_templates(self, waba_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetches approved message templates for WABA account."""
        target_waba = waba_id or ALOTS_WABA_ID
        if not target_waba:
            return {"error": {"message": "WABA ID is not configured."}}
        return self._get(f"{target_waba}/message_templates")
