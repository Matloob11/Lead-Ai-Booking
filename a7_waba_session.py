"""
A7 WhatsApp Business API Session & Line Manager
Handles SQLite persistent session tracking for 24-hour Meta session windows,
phone-number-to-agent/line routing, and message logging.
"""

import sqlite3
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple
from a7_waba_config import DB_PATH, SESSION_WINDOW_HOURS, load_line_mappings, save_line_mappings

logger = logging.getLogger("a7_waba_session")


class WABAStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Sessions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_sessions (
                    client_phone TEXT PRIMARY KEY,
                    phone_number_id TEXT,
                    line_id TEXT,
                    last_client_msg_ts TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Line Mappings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS line_mappings (
                    phone_number_id TEXT PRIMARY KEY,
                    line_id TEXT,
                    label TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Message Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT,
                    client_phone TEXT,
                    phone_number_id TEXT,
                    line_id TEXT,
                    direction TEXT, -- 'inbound' or 'outbound'
                    msg_type TEXT,  -- 'text', 'image', 'document', 'template', etc.
                    content TEXT,
                    status TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    # --- Line Mapping Methods ---

    def set_line_mapping(self, phone_number_id: str, line_id: str, label: str = "") -> None:
        phone_number_id = str(phone_number_id).strip()
        line_id = str(line_id).strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO line_mappings (phone_number_id, line_id, label, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(phone_number_id) DO UPDATE SET
                    line_id = excluded.line_id,
                    label = excluded.label,
                    updated_at = CURRENT_TIMESTAMP
            """, (phone_number_id, line_id, label))
            conn.commit()
            
        # Update json fallback
        current_map = load_line_mappings()
        current_map[phone_number_id] = line_id
        save_line_mappings(current_map)

    def get_line_id(self, phone_number_id: str, default_line: str = "1") -> str:
        phone_number_id = str(phone_number_id).strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT line_id FROM line_mappings WHERE phone_number_id = ?", (phone_number_id,))
            row = cursor.fetchone()
            if row and row["line_id"]:
                return str(row["line_id"])
        
        # Fallback to json configuration or default
        json_mappings = load_line_mappings()
        return json_mappings.get(phone_number_id, default_line)

    def list_line_mappings(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number_id, line_id, label, updated_at FROM line_mappings")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # --- Session Window Methods ---

    def touch_client_session(self, client_phone: str, phone_number_id: str, line_id: str) -> None:
        client_phone = str(client_phone).strip().lstrip("+")
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO client_sessions (client_phone, phone_number_id, line_id, last_client_msg_ts, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(client_phone) DO UPDATE SET
                    phone_number_id = excluded.phone_number_id,
                    line_id = excluded.line_id,
                    last_client_msg_ts = excluded.last_client_msg_ts,
                    updated_at = excluded.updated_at
            """, (client_phone, str(phone_number_id), str(line_id), now_str, now_str))
            conn.commit()

    @staticmethod
    def _parse_ts(raw_ts: Any) -> datetime.datetime:
        """Normalises a stored timestamp into a timezone-aware UTC datetime."""
        if isinstance(raw_ts, str):
            try:
                parsed = datetime.datetime.fromisoformat(raw_ts)
            except ValueError:
                parsed = datetime.datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
        else:
            parsed = raw_ts

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed

    def get_client_session(self, client_phone: str) -> Optional[Dict[str, Any]]:
        """
        Returns the raw session row for a client phone, or None if the client
        has never messaged in. Used by the widget session-status endpoint, which
        needs second-level precision rather than the rounded hours returned by
        is_24h_window_active().
        """
        client_phone = str(client_phone).strip().lstrip("+")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT client_phone, phone_number_id, line_id, last_client_msg_ts
                FROM client_sessions WHERE client_phone = ?
            """, (client_phone,))
            row = cursor.fetchone()
            if not row or not row["last_client_msg_ts"]:
                return None

            session = dict(row)
            session["last_client_msg_ts"] = self._parse_ts(row["last_client_msg_ts"])
            return session

    def is_24h_window_active(self, client_phone: str) -> Tuple[bool, Optional[float]]:
        """
        Checks if 24h session window is active.
        Returns: (is_active: bool, remaining_hours: Optional[float])
        """
        client_phone = str(client_phone).strip().lstrip("+")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_client_msg_ts FROM client_sessions WHERE client_phone = ?", (client_phone,))
            row = cursor.fetchone()
            if not row or not row["last_client_msg_ts"]:
                return False, 0.0

            last_ts = self._parse_ts(row["last_client_msg_ts"])
            now = datetime.datetime.now(datetime.timezone.utc)
            elapsed_seconds = (now - last_ts).total_seconds()
            max_seconds = SESSION_WINDOW_HOURS * 3600.0

            if elapsed_seconds <= max_seconds:
                remaining_hours = round((max_seconds - elapsed_seconds) / 3600.0, 2)
                return True, remaining_hours
            else:
                return False, 0.0

    # --- Message Logging Methods ---

    def log_message(self, msg_id: str, client_phone: str, phone_number_id: str, line_id: str,
                    direction: str, msg_type: str, content: str, status: str = "sent") -> None:
        client_phone = str(client_phone).strip().lstrip("+")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO message_logs (msg_id, client_phone, phone_number_id, line_id, direction, msg_type, content, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (msg_id, client_phone, str(phone_number_id), str(line_id), direction, msg_type, content, status))
            conn.commit()

    def get_recent_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM message_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
