"""Ratings workflow route for reviewing discharge summaries."""

from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse

from eval_v2.config import TEMPLATES_DIR
from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.review_completion import recompute_and_persist
from eval_v2.services.doctor_lookup import get_doctor_id_for_user
from eval_v2.services.example_case import is_example_read_only
from eval_v2.services.activity_log import log_activity

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Valid rating fields that can be updated
VALID_RATING_FIELDS = {
    "human_quality", "human_conciseness", "human_readability", "human_clarity", "human_factuality",
    "human_completeness", "human_easy_understand", "human_easy_verbalize", "human_easy_follow_up",
    "ai_quality", "ai_conciseness", "ai_readability", "ai_clarity", "ai_factuality",
    "ai_completeness", "ai_easy_understand", "ai_easy_verbalize", "ai_easy_follow_up",
    "overall_preference",
}


def get_review_data(encounter_number: int, doctor_id: int) -> dict | None:
    """Fetch review data for an encounter/doctor pair."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                r.encounter_number,
                r.patient_age,
                r.patient_gender,
                r.LOS,
                r.review_completed,
                r.first_look,
                r.human_quality, r.human_conciseness, r.human_readability, r.human_clarity, r.human_factuality,
                r.human_completeness, r.human_easy_understand, r.human_easy_verbalize, r.human_easy_follow_up,
                r.ai_quality, r.ai_conciseness, r.ai_readability, r.ai_clarity, r.ai_factuality,
                r.ai_completeness, r.ai_easy_understand, r.ai_easy_verbalize, r.ai_easy_follow_up,
                r.overall_preference, r.overall_preference_comment,
                d.is_pcp
            FROM reviews_to_complete r
            JOIN doctors d ON r.doctor_id = d.id
            WHERE r.encounter_number = ? AND r.doctor_id = ?
            """,
            (encounter_number, doctor_id),
        )
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "encounter_number": row[0],
            "patient_age": row[1],
            "patient_gender": row[2],
            "los": row[3],
            "review_completed": row[4] == 1,
            "first_look": row[5] or "Human",
            "human_quality": row[6],
            "human_conciseness": row[7],
            "human_readability": row[8],
            "human_clarity": row[9],
            "human_factuality": row[10],
            "human_completeness": row[11],
            "human_easy_understand": row[12],
            "human_easy_verbalize": row[13],
            "human_easy_follow_up": row[14],
            "ai_quality": row[15],
            "ai_conciseness": row[16],
            "ai_readability": row[17],
            "ai_clarity": row[18],
            "ai_factuality": row[19],
            "ai_completeness": row[20],
            "ai_easy_understand": row[21],
            "ai_easy_verbalize": row[22],
            "ai_easy_follow_up": row[23],
            "overall_preference": row[24],
            "overall_preference_comment": row[25],
            "is_pcp": row[26] == 1,
        }


def update_rating(encounter_number: int, doctor_id: int, field: str, value: int) -> bool:
    """Update a single rating field in the database."""
    if field not in VALID_RATING_FIELDS:
        return False

    with get_connection() as conn:
        cursor = conn.cursor()
        # Use parameterized field name (safe because we validated against whitelist)
        cursor.execute(
            f"UPDATE reviews_to_complete SET {field} = ? WHERE encounter_number = ? AND doctor_id = ?",
            (value, encounter_number, doctor_id),
        )
        conn.commit()
        return cursor.rowcount > 0


@router.get("/ratings")
async def ratings(
    request: Request,
    encounter_number: int | None = Query(None),
    user: dict = Depends(manager),
):
    """Compatibility redirect to the document viewer workflow."""
    if encounter_number is None:
        return RedirectResponse(url="/overview", status_code=302)

    return RedirectResponse(
        url=f"/documents?encounter_number={encounter_number}",
        status_code=302,
    )


@router.post("/ratings/{encounter_number}/{doctor_id}/update")
async def update_rating_field(
    request: Request,
    encounter_number: int,
    doctor_id: int,
    field: str = Form(...),
    value: int = Form(...),
    user: dict = Depends(manager),
):
    """Update a single rating field via HTMX."""
    authorized_doctor_id = get_doctor_id_for_user(user)
    if not authorized_doctor_id or authorized_doctor_id != doctor_id:
        return Response(status_code=403, content="Forbidden")

    if not get_review_data(encounter_number, doctor_id):
        return Response(status_code=404, content="Review not found")

    if is_example_read_only(encounter_number):
        return Response(status_code=403, content="Example case is read-only")

    if field not in VALID_RATING_FIELDS:
        return Response(status_code=400, content="Invalid field")

    # overall_preference uses 0/1 values, other ratings use 1-5
    if field == "overall_preference":
        if value not in (0, 1):
            return Response(status_code=400, content="Invalid value")
    else:
        if value < 1 or value > 5:
            return Response(status_code=400, content="Invalid value")

    update_rating(encounter_number, doctor_id, field, value)

    completion = recompute_and_persist(encounter_number, doctor_id)
    log_activity(
        "rating_updated",
        doctor_id=doctor_id,
        username=user.get("username"),
        email=user.get("email"),
        encounter_number=encounter_number,
        details={"field": field, "value": value},
    )
    return templates.TemplateResponse(
        "partials/review_status_badge.html",
        {
            "request": request,
            "review_completed": completion.completed,
            "badge_id": "review-status-badge",
        },
    )


@router.post("/ratings/{encounter_number}/{doctor_id}/preference-comment")
async def update_preference_comment(
    request: Request,
    encounter_number: int,
    doctor_id: int,
    comment_text: str | None = Form(None),
    user: dict = Depends(manager),
):
    """Update the overall preference comment via HTMX."""
    normalized_comment = comment_text or ""
    authorized_doctor_id = get_doctor_id_for_user(user)
    if not authorized_doctor_id or authorized_doctor_id != doctor_id:
        return Response(status_code=403, content="Forbidden")

    if not get_review_data(encounter_number, doctor_id):
        return Response(status_code=404, content="Review not found")

    if is_example_read_only(encounter_number):
        return Response(status_code=403, content="Example case is read-only")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reviews_to_complete
            SET overall_preference_comment = ?
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (normalized_comment, encounter_number, doctor_id),
        )
        conn.commit()

    completion = recompute_and_persist(encounter_number, doctor_id)
    log_activity(
        "preference_comment_updated",
        doctor_id=doctor_id,
        username=user.get("username"),
        email=user.get("email"),
        encounter_number=encounter_number,
        details={"comment_text": normalized_comment},
    )
    return templates.TemplateResponse(
        "partials/review_status_badge.html",
        {
            "request": request,
            "review_completed": completion.completed,
            "badge_id": "review-status-badge",
        },
    )
