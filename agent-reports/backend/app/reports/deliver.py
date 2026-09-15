"""Upload PDFs to Bitrix Disk and notify managers on Messenger."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from ..bitrix.client import BitrixClient, BitrixError
from ..config import get_settings

logger = logging.getLogger(__name__)


def _root_folder_id(client: BitrixClient) -> int | None:
    storages = client.call("disk.storage.getlist") or []
    if not isinstance(storages, list):
        return None
    for st in storages:
        root = st.get("ROOT_OBJECT_ID") or st.get("rootObjectId")
        if root:
            try:
                return int(root)
            except (TypeError, ValueError):
                continue
    return None


def upload_pdf(client: BitrixClient, path: Path, remote_name: str) -> str:
    """Return Bitrix disk file id (string) or empty on failure."""
    folder_id = _root_folder_id(client)
    if not folder_id:
        raise BitrixError("disk.storage.getlist", "NO_STORAGE", "No disk storage root found")
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    result = client.call(
        "disk.folder.uploadfile",
        {
            "id": folder_id,
            "data": {"NAME": remote_name},
            "fileContent": [remote_name, b64],
        },
    )
    if isinstance(result, dict):
        fid = result.get("ID") or result.get("id")
        return str(fid or "")
    return ""


def notify_recipients(client: BitrixClient, message: str, user_ids: list[int] | None = None) -> list[int]:
    settings = get_settings()
    targets = user_ids if user_ids is not None else settings.messenger_user_id_list()
    ok: list[int] = []
    for uid in targets:
        try:
            client.call(
                "im.notify.system.add",
                {"USER_ID": uid, "MESSAGE": message[:2000]},
            )
            ok.append(uid)
        except BitrixError as exc:
            logger.warning("Notify failed for user %s: %s", uid, exc)
    return ok


def deliver_digest(
    client: BitrixClient,
    *,
    day: str,
    lines: list[str],
    pdf_note: str = "",
) -> list[int]:
    body = (
        f"A7 Agent Daily Reports — {day}\n\n"
        + "\n".join(lines[:80])
        + ("\n\n" + pdf_note if pdf_note else "")
        + "\n\nOpen Agent Report in Bitrix for full PDF history."
    )
    return notify_recipients(client, body)
