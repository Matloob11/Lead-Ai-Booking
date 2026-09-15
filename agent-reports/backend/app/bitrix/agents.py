"""Resolve Sales / TS agents from configured Bitrix department IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import BitrixClient


@dataclass(frozen=True)
class Agent:
    id: int
    name: str
    email: str
    department_ids: tuple[int, ...]
    department_names: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "department_ids": list(self.department_ids),
            "department_names": list(self.department_names),
        }


def _dept_map(client: BitrixClient) -> dict[int, str]:
    rows = client.call("department.get") or []
    out: dict[int, str] = {}
    for row in rows:
        try:
            out[int(row["ID"])] = str(row.get("NAME") or "")
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _active_users(client: BitrixClient) -> list[dict[str, Any]]:
    return client.call_list("user.get", {"FILTER": {"ACTIVE": "true"}})


def _user_dept_ids(user: dict[str, Any]) -> list[int]:
    raw = user.get("UF_DEPARTMENT") or []
    if not isinstance(raw, list):
        raw = [raw]
    ids: list[int] = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _display_name(user: dict[str, Any]) -> str:
    parts = [str(user.get("NAME") or "").strip(), str(user.get("LAST_NAME") or "").strip()]
    name = " ".join(p for p in parts if p).strip()
    return name or str(user.get("EMAIL") or user.get("ID") or "Unknown")


def list_sales_ts_agents(client: BitrixClient, dept_ids: list[int]) -> list[Agent]:
    """Active Bitrix users whose department intersects the configured Sales/TS set."""
    wanted = {int(x) for x in dept_ids}
    if not wanted:
        return []
    names = _dept_map(client)
    agents: list[Agent] = []
    seen: set[int] = set()
    for user in _active_users(client):
        try:
            uid = int(user["ID"])
        except (KeyError, TypeError, ValueError):
            continue
        if uid in seen:
            continue
        depts = _user_dept_ids(user)
        if not wanted.intersection(depts):
            continue
        seen.add(uid)
        agents.append(
            Agent(
                id=uid,
                name=_display_name(user),
                email=str(user.get("EMAIL") or ""),
                department_ids=tuple(depts),
                department_names=tuple(names.get(d, str(d)) for d in depts),
            )
        )
    agents.sort(key=lambda a: a.name.lower())
    return agents
