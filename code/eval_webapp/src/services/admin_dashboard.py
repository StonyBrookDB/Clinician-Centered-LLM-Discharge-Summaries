"""Admin dashboard queries for overview page."""

from __future__ import annotations

from typing import Any

from eval_v2.services.db_connection import get_connection
from eval_v2.services.activity_log import fetch_recent_activity
from eval_v2.services.example_case import EXAMPLE_ENCOUNTER_NUMBERS, is_example_encounter
from eval_v2.services.dummy_account import DUMMY_DOCTOR_ID, is_dummy_encounter


_ACTION_LABELS = {
    "rating_updated": "Rating updated",
    "incidental_updated": "Incidental finding updated",
    "incidental_comment_updated": "Incidental comment updated",
    "highlight_created": "Highlight created",
    "highlight_updated": "Highlight updated",
    "highlight_deleted": "Highlight deleted",
    "annotation_created": "Annotation created",
    "annotation_updated": "Annotation updated",
    "annotation_deleted": "Annotation deleted",
    "annotation_status_updated": "Annotation status updated",
}


def _format_activity_detail(action_type: str, details: dict[str, Any] | None) -> str:
    if not details:
        return ""
    if action_type in {"rating_updated", "incidental_updated"}:
        field = details.get("field")
        value = details.get("value")
        if field is not None and value is not None:
            return f"{field} = {value}"
    if action_type == "annotation_status_updated":
        status = details.get("status")
        if status:
            return f"status = {status}"
    highlight_id = details.get("highlight_id")
    if highlight_id is not None:
        return f"id {highlight_id}"
    annotation_id = details.get("annotation_id")
    if annotation_id is not None:
        return f"id {annotation_id}"
    return ""


def _example_encounter_placeholders() -> tuple[str, list[Any]]:
    example_numbers = sorted(EXAMPLE_ENCOUNTER_NUMBERS)
    if not example_numbers:
        return "", []
    placeholders = ",".join("?" for _ in example_numbers)
    return f"({placeholders})", list(example_numbers)


def fetch_admin_summary(*, exclude_doctor_id: int | None = None) -> list[dict[str, Any]]:
    placeholders, params = _example_encounter_placeholders()
    join_filter = ""
    if placeholders:
        join_filter = f"AND r.encounter_number NOT IN {placeholders}"
    with get_connection(read_only=True) as conn:
        conn.row_factory = lambda cursor, row: {
            "doctor_id": row[0],
            "email": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "total_assigned": row[4],
            "completed_assigned": row[5],
        }
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                d.id,
                d.email,
                d.first_name,
                d.last_name,
                COUNT(r.encounter_number) AS total_assigned,
                SUM(CASE WHEN r.review_completed = 1 THEN 1 ELSE 0 END) AS completed_assigned
            FROM doctors d
            LEFT JOIN reviews_to_complete r
                ON r.doctor_id = d.id
                {join_filter}
            GROUP BY d.id
            ORDER BY d.id
            """
        ,
            params,
        )
        rows = cursor.fetchall()

    summary: list[dict[str, Any]] = []
    for row in rows:
        if row["doctor_id"] == DUMMY_DOCTOR_ID:
            continue
        if exclude_doctor_id and row["doctor_id"] == exclude_doctor_id:
            continue
        total = row["total_assigned"] or 0
        completed = row["completed_assigned"] or 0
        percent = int(round((completed / total) * 100)) if total else 0
        summary.append(
            {
                **row,
                "completion_percent": percent,
            }
        )
    return summary


def fetch_admin_assignments(*, exclude_doctor_id: int | None = None) -> list[dict[str, Any]]:
    placeholders, params = _example_encounter_placeholders()
    where_clause = ""
    if placeholders:
        where_clause = f"WHERE r.encounter_number NOT IN {placeholders}"
    with get_connection(read_only=True) as conn:
        conn.row_factory = lambda cursor, row: {
            "doctor_id": row[0],
            "email": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "encounter_number": row[4],
            "review_completed": row[5] == 1,
            "first_look": row[6],
            "patient_age": row[7],
            "patient_gender": row[8],
            "los": row[9],
            "findings_count": row[10] or 0,
        }
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                d.id,
                d.email,
                d.first_name,
                d.last_name,
                r.encounter_number,
                r.review_completed,
                r.first_look,
                r.patient_age,
                r.patient_gender,
                r.LOS,
                (
                    SELECT COUNT(*)
                    FROM incidental_findings i
                    WHERE i.encounter_id = r.encounter_number
                      AND i.doctor_id = d.id
                ) AS findings_count
            FROM reviews_to_complete r
            JOIN doctors d ON r.doctor_id = d.id
            {where_clause}
            ORDER BY d.last_name, d.first_name, r.LOS ASC, r.encounter_number
            """
        ,
            params,
        )
        rows = cursor.fetchall()

    if exclude_doctor_id:
        rows = [row for row in rows if row["doctor_id"] != exclude_doctor_id]
    rows = [row for row in rows if row["doctor_id"] != DUMMY_DOCTOR_ID]
    return rows


def fetch_admin_activity(*, limit: int = 50, exclude_doctor_id: int | None = None) -> list[dict[str, Any]]:
    events = fetch_recent_activity(limit=limit, exclude_doctor_id=exclude_doctor_id)
    formatted: list[dict[str, Any]] = []
    for event in events:
        if event.get("doctor_id") == DUMMY_DOCTOR_ID:
            continue
        encounter_number = event.get("encounter_number")
        if encounter_number is not None and (
            is_example_encounter(encounter_number) or is_dummy_encounter(encounter_number)
        ):
            continue
        action_type = event["action_type"]
        first_name = event.get("first_name") or ""
        last_name = event.get("last_name") or ""
        reviewer_label = f"{first_name} {last_name}".strip()
        if not reviewer_label:
            reviewer_label = event.get("username") or event.get("email") or "Unknown"
        detail = _format_activity_detail(action_type, event.get("details"))
        formatted.append(
            {
                **event,
                "action_label": _ACTION_LABELS.get(action_type, action_type.replace("_", " ").title()),
                "detail_text": detail,
                "reviewer_label": reviewer_label,
            }
        )
    return formatted


__all__ = ["fetch_admin_summary", "fetch_admin_assignments", "fetch_admin_activity"]
