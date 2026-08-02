"""
Bitrix24 Open Channels `imconnector` REST API Client
Handles connector registration, activation, and message delivery into Bitrix24 Open Lines.
"""

import time
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Optional
from a7_waba_config import BITRIX_REST_URL, CONNECTOR_ID

logger = logging.getLogger("a7_waba_bitrix_client")


class BitrixConnectorClient:
    def __init__(self, rest_url: str = BITRIX_REST_URL, connector_id: str = CONNECTOR_ID):
        self.rest_url = rest_url.rstrip("/")
        self.connector_id = connector_id

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.rest_url:
            logger.error("BITRIX_REST_URL is not set!")
            return {"error": "BITRIX_REST_URL_NOT_CONFIGURED"}

        url = f"{self.rest_url}/{method}"
        data_bytes = json.dumps(params).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                res_data = resp.read().decode("utf-8")
                return json.loads(res_data) if res_data else {}
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8") if err.fp else ""
            logger.error(f"HTTPError calling Bitrix {method}: status={err.code}, body={err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"error": f"HTTP {err.code}: {err_body}"}
        except Exception as err:
            logger.error(f"Error calling Bitrix {method}: {err}")
            return {"error": str(err)}

    def register_connector(self, title: str = "WhatsApp Business API (ALOTS.IO)", icon_url: str = "") -> Dict[str, Any]:
        """Registers the custom connector in Bitrix24."""
        params = {
            "ID": self.connector_id,
            "NAME": title,
            "ICON": {
                "DATA_IMAGE": icon_url
            }
        }
        return self._call("imconnector.register", params)

    def activate_line(self, line_id: str, active: int = 1) -> Dict[str, Any]:
        """Activates/deactivates the connector for a specific Bitrix Open Line."""
        params = {
            "CONNECTOR": self.connector_id,
            "LINE": str(line_id),
            "ACTIVE": active
        }
        return self._call("imconnector.activate", params)

    def send_inbound_message(self, line_id: str, client_phone: str, client_name: str,
                             msg_id: str, text: str, files: Optional[List[Dict[str, Any]]] = None,
                             timestamp: Optional[int] = None) -> Dict[str, Any]:
        """
        Delivers an incoming WhatsApp message into Bitrix Open Channels.
        files format: [{"url": "https://...", "name": "filename.png"}]
        """
        client_phone_clean = client_phone.lstrip("+").strip()
        user_id = f"wa_{client_phone_clean}"
        chat_id = f"wa_chat_{client_phone_clean}"
        msg_timestamp = timestamp or int(time.time())

        message_obj: Dict[str, Any] = {
            "id": msg_id,
            "date": msg_timestamp,
            "text": text or ""
        }

        if files:
            message_obj["files"] = files

        payload = {
            "CONNECTOR": self.connector_id,
            "LINE": str(line_id),
            "MESSAGES": [
                {
                    "user": {
                        "id": user_id,
                        "name": client_name or f"+{client_phone_clean}",
                        "phone": client_phone_clean,
                        "avatar": ""
                    },
                    "message": message_obj,
                    "chat": {
                        "id": chat_id,
                        "url": ""
                    }
                }
            ]
        }

        logger.info(f"Delivering inbound message to Bitrix Line {line_id} for {client_phone_clean}")
        return self._call("imconnector.send.messages", payload)

    def send_status(self, line_id: str, msg_id: str, status: str = "delivered") -> Dict[str, Any]:
        """Sends status update (delivered, read) to Bitrix."""
        params = {
            "CONNECTOR": self.connector_id,
            "LINE": str(line_id),
            "STATUS": [
                {
                    "id": msg_id,
                    "status": status
                }
            ]
        }
        return self._call("imconnector.send.status", params)
