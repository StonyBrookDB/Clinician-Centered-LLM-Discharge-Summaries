"""Activity logging for review actions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from eval_v2.services.db_connection import get_connection


logger = logging.getLogger(__name__)


def ensure_activity_log_schema(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS review_activity_log (
            activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER,
            username TEXT,
            email TEXT,
            encounter_number INTEGER,
            action_type TEXT NOT NULL,
            details_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(doctor_id) REFERENCES doctors(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_review_activity_created_at
        ON review_activity_log (created_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_review_activity_doctor_id
        ON review_activity_log (doctor_id)
        """
    )
    conn.commit()


def log_activity(
    action_type: str,
    *,
    doctor_id: int | None,
    username: str | None,
    email: str | None,
    encounter_number: int | None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an activity event; failures are logged but do not raise."""
    if not action_type:
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    details_json = json.dumps(details, ensure_ascii=True) if details else None

    try:
        with get_connection() as conn:
            ensure_activity_log_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO review_activity_log
                (doctor_id, username, email, encounter_number, action_type, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doctor_id,
                    username,
                    email,
                    encounter_number,
                    action_type,
                    details_json,
                    timestamp,
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to record activity log entry.")


def fetch_recent_activity(
    *,
    limit: int = 50,
    exclude_doctor_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent activity events, optionally excluding a doctor."""
    with get_connection() as conn:
        ensure_activity_log_schema(conn)
        cursor = conn.cursor()
        if exclude_doctor_id is None:
            cursor.execute(
                """
                SELECT
                    a.activity_id,
                    a.doctor_id,
                    a.username,
                    a.email,
                    a.encounter_number,
                    a.action_type,
                    a.details_json,
                    a.created_at,
                    d.first_name,
                    d.last_name
                FROM review_activity_log a
                LEFT JOIN doctors d ON a.doctor_id = d.id
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    a.activity_id,
                    a.doctor_id,
                    a.username,
                    a.email,
                    a.encounter_number,
                    a.action_type,
                    a.details_json,
                    a.created_at,
                    d.first_name,
                    d.last_name
                FROM review_activity_log a
                LEFT JOIN doctors d ON a.doctor_id = d.id
                WHERE a.doctor_id IS NULL OR a.doctor_id != ?
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (exclude_doctor_id, limit),
            )

        rows = cursor.fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        (
            activity_id,
            doctor_id,
            username,
            email,
            encounter_number,
            action_type,
            details_json,
            created_at,
            first_name,
            last_name,
        ) = row
        details = None
        if details_json:
            try:
                details = json.loads(details_json)
            except json.JSONDecodeError:
                details = None
        events.append(
            {
                "activity_id": activity_id,
                "doctor_id": doctor_id,
                "username": username,
                "email": email,
                "encounter_number": encounter_number,
                "action_type": action_type,
                "details": details,
                "created_at": created_at,
                "first_name": first_name,
                "last_name": last_name,
            }
        )
    return events


__all__ = ["ensure_activity_log_schema", "log_activity", "fetch_recent_activity"]
