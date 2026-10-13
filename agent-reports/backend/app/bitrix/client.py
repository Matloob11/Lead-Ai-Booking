"""Minimal Bitrix24 REST client for inbound webhooks."""

from __future__ import annotations

from typing import Any

import httpx


class BitrixError(Exception):
    def __init__(self, method: str, error: str, description: str = ""):
        self.method = method
        self.error = error
        self.description = description
        super().__init__(f"{method}: {error} {description}".strip())


class BitrixClient:
    def __init__(self, webhook_base: str, *, timeout: float = 120.0):
        base = (webhook_base or "").rstrip("/")
        if not base:
            raise ValueError("Bitrix webhook base URL is empty")
        self.base = base
        self.timeout = timeout

    def call_list(self, method: str, params: dict[str, Any] | None = None) -> list[Any]:
        """Paginate Bitrix list methods that return `next`."""
        params = dict(params or {})
        start = int(params.get("start") or 0)
        rows: list[Any] = []
        while True:
            params["start"] = start
            payload = self._post(method, params)
            batch = payload.get("result") if isinstance(payload, dict) else payload
            if isinstance(batch, dict) and "tasks" in batch:
                items = batch.get("tasks") or []
            elif isinstance(batch, dict) and "items" in batch:
                items = batch.get("items") or []
            elif isinstance(batch, list):
                items = batch
            else:
                items = batch or []
            if isinstance(items, list):
                rows.extend(items)
            nxt = payload.get("next") if isinstance(payload, dict) else None
            if nxt is None:
                break
            start = int(nxt)
        return rows

    def call_total(self, method: str, params: dict[str, Any] | None = None) -> int:
        """Return Bitrix `total` for a list method (first page only)."""
        params = dict(params or {})
        params.setdefault("start", 0)
        payload = self._post(method, params)
        if payload.get("total") is not None:
            return int(payload["total"])
        result = payload.get("result")
        if isinstance(result, dict) and "items" in result:
            return len(result.get("items") or [])
        if isinstance(result, dict) and "tasks" in result:
            return len(result.get("tasks") or [])
        if isinstance(result, list):
            return len(result)
        return 0

    def _post(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base}/{method.lstrip('/')}.json"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=params)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise BitrixError(
                method,
                str(payload.get("error")),
                str(payload.get("error_description") or ""),
            )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = self._post(method, params or {})
        return payload.get("result")
