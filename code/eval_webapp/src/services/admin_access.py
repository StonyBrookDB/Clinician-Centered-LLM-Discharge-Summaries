"""Admin access helpers for restricted UI features."""

from __future__ import annotations

import os


_ADMIN_USERNAMES_ENV = "ADMIN_USERNAMES"


def _normalize_username(value: str | None) -> str:
    return (value or "").strip().lower()


def get_admin_usernames() -> set[str]:
    raw = os.getenv(_ADMIN_USERNAMES_ENV, "").strip()
    if not raw:
        return set()
    parts = {item.strip().lower() for item in raw.replace(";", ",").split(",")}
    return {item for item in parts if item}


def is_admin_user(user: dict) -> bool:
    username = _normalize_username(user.get("username"))
    if not username:
        return False
    return username in get_admin_usernames()


__all__ = ["get_admin_usernames", "is_admin_user"]
