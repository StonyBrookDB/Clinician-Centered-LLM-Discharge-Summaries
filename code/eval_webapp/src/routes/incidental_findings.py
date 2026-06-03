"""Incidental findings evaluation routes."""

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from eval_v2.config import TEMPLATES_DIR
from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.review_completion import recompute_and_persist
from eval_v2.services.doctor_lookup import get_doctor_id_for_user
from eval_v2.services.example_case import is_example_read_only
from eval_v2.services.activity_log import log_activity

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_incidental_findings(encounter_number: int, doctor_id: int) -> list[dict]:
    """Fetch incidental findings for an encounter/doctor pair."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT if_id, content, factuality, clinical_importance, clinical_importance_comment
            FROM incidental_findings
            WHERE encounter_id = ? AND doctor_id = ?
            ORDER BY if_id
            """,
            (encounter_number, doctor_id),
        )
        rows = cursor.fetchall()
        return [
            {
                "if_id": row[0],
                "content": row[1],
                "factuality": row[2],  # -1=unanswered, 0=No, 1=Yes, 2=Unsure
                "clinical_importance": row[3],  # -1=unanswered, 0=No, 1=Yes, 2=Unsure
                "clinical_importance_comment": row[4],
            }
            for row in rows
        ]


def update_incidental_finding(if_id: int, field: str, value: int) -> bool:
    """Update a single incidental finding field."""
    if field not in ("factuality", "clinical_importance"):
        return False
    if value not in (-1, 0, 1, 2):
        return False

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE incidental_findings SET {field} = ? WHERE if_id = ?",
            (value, if_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_incidental_finding_comment(if_id: int, comment_text: str | None) -> bool:
    """Update the clinical importance comment for an incidental finding."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE incidental_findings
            SET clinical_importance_comment = ?
            WHERE if_id = ?
            """,
            (comment_text, if_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def _get_review_key_for_finding(if_id: int) -> tuple[int, int] | None:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT encounter_id, doctor_id
            FROM incidental_findings
            WHERE if_id = ?
            """,
            (if_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return int(row[0]), int(row[1])


@router.post("/incidental-findings/{if_id}/update")
async def update_finding(
    request: Request,
    if_id: int,
    field: str = Form(...),
    value: int = Form(...),
    user: dict = Depends(manager),
):
    """Update an incidental finding field via HTMX."""
    if field not in ("factuality", "clinical_importance"):
        return Response(status_code=400, content="Invalid field")

    if value not in (-1, 0, 1, 2):
        return Response(status_code=400, content="Invalid value")

    review_key = _get_review_key_for_finding(if_id)
    if not review_key:
        return Response(status_code=404, content="Incidental finding not found")
    encounter_number, doctor_id = review_key
    authorized_doctor_id = get_doctor_id_for_user(user)
    if not authorized_doctor_id or authorized_doctor_id != doctor_id:
        return Response(status_code=403, content="Forbidden")

    if is_example_read_only(encounter_number):
        return Response(status_code=403, content="Example case is read-only")

    update_incidental_finding(if_id, field, value)

    completion = recompute_and_persist(encounter_number, doctor_id)
    log_activity(
        "incidental_updated",
        doctor_id=doctor_id,
        username=user.get("username"),
        email=user.get("email"),
        encounter_number=encounter_number,
        details={"field": field, "value": value, "if_id": if_id},
    )
    return templates.TemplateResponse(
        "partials/review_status_badge.html",
        {
            "request": request,
            "review_completed": completion.completed,
            "badge_id": "review-status-badge",
        },
    )


@router.post("/incidental-findings/{if_id}/comment")
async def update_finding_comment(
    request: Request,
    if_id: int,
    comment_text: str | None = Form(None),
    user: dict = Depends(manager),
):
    """Update the comment for an incidental finding via HTMX."""
    review_key = _get_review_key_for_finding(if_id)
    if not review_key:
        return Response(status_code=404, content="Incidental finding not found")
    encounter_number, doctor_id = review_key
    authorized_doctor_id = get_doctor_id_for_user(user)
    if not authorized_doctor_id or authorized_doctor_id != doctor_id:
        return Response(status_code=403, content="Forbidden")

    if is_example_read_only(encounter_number):
        return Response(status_code=403, content="Example case is read-only")

    normalized_comment = (comment_text or "").strip() or None
    update_incidental_finding_comment(if_id, normalized_comment)

    completion = recompute_and_persist(encounter_number, doctor_id)
    log_activity(
        "incidental_comment_updated",
        doctor_id=doctor_id,
        username=user.get("username"),
        email=user.get("email"),
        encounter_number=encounter_number,
        details={"if_id": if_id, "has_comment": bool(normalized_comment)},
    )
    return templates.TemplateResponse(
        "partials/review_status_badge.html",
        {
            "request": request,
            "review_completed": completion.completed,
            "badge_id": "review-status-badge",
        },
    )
