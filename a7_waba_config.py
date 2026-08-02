"""
A7 Bitrix24 WhatsApp Business API (Omni Channel) Connector Configuration
Supports ALOTS.IO / Meta WABA Cloud API v23.0 & Bitrix24 imconnector module.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("a7_waba_config")

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

DB_PATH = os.getenv("A7_WABA_DB_PATH", str(DATA_DIR / "waba_connector.db"))

# ALOTS.IO / Meta WABA API Configuration
ALOTS_BASE_URL = os.getenv("ALOTS_BASE_URL", "https://alots.io").rstrip("/")
ALOTS_API_KEY = os.getenv("ALOTS_API_KEY", "")
ALOTS_VERSION = os.getenv("ALOTS_VERSION", "v23.0")
ALOTS_WABA_ID = os.getenv("ALOTS_WABA_ID", "")
ALOTS_WEBHOOK_SECRET = os.getenv("ALOTS_WEBHOOK_SECRET", "")

# Bitrix24 Configuration
BITRIX_REST_URL = os.getenv("BITRIX_REST_URL", "").rstrip("/")
CONNECTOR_ID = os.getenv("A7_WABA_CONNECTOR_ID", "a7_whatsapp_omni")

# Session & Routing Configuration
SESSION_WINDOW_HOURS = int(os.getenv("A7_WABA_SESSION_WINDOW_HOURS", "24"))

# Default Line Mapping (Phone Number ID -> Bitrix Open Line ID)
# Format: {"phoneNumberId_or_phone": bitrix_line_id}
DEFAULT_LINE_MAPPINGS_JSON = os.getenv("A7_WABA_LINE_MAPPINGS", "{}")


def load_line_mappings() -> Dict[str, str]:
    """Loads line mappings from environment or config file."""
    try:
        mappings = json.loads(DEFAULT_LINE_MAPPINGS_JSON)
        if isinstance(mappings, dict):
            return {str(k): str(v) for k, v in mappings.items()}
    except Exception as err:
        logger.warning(f"Failed to parse A7_WABA_LINE_MAPPINGS env var: {err}")
    
    mapping_file = DATA_DIR / "line_mappings.json"
    if mapping_file.exists():
        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except Exception as err:
            logger.error(f"Error reading line_mappings.json: {err}")
            
    return {}


def save_line_mappings(mappings: Dict[str, str]) -> None:
    """Saves line mappings to data directory."""
    mapping_file = DATA_DIR / "line_mappings.json"
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2)


def get_config_summary() -> Dict[str, Any]:
    return {
        "alots_base_url": ALOTS_BASE_URL,
        "alots_version": ALOTS_VERSION,
        "alots_waba_id": ALOTS_WABA_ID,
        "connector_id": CONNECTOR_ID,
        "session_window_hours": SESSION_WINDOW_HOURS,
        "bitrix_configured": bool(BITRIX_REST_URL),
        "db_path": DB_PATH,
    }
