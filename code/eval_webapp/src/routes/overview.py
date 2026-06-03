"""Overview dashboard route showing encounters assigned to the logged-in reviewer."""

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates

from eval_v2.config import TEMPLATES_DIR
from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.doctor_lookup import get_doctor_id_by_email
from eval_v2.services.example_case import EXAMPLE_ENCOUNTER_NUMBERS
from eval_v2.services.admin_access import is_admin_user
from eval_v2.services.admin_dashboard import (
    fetch_admin_summary,
    fetch_admin_assignments,
    fetch_admin_activity,
)
from eval_v2.services.notes_loader import load_encounter_documents

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_encounters_for_doctor(doctor_id: int) -> list[dict]:
    """Fetch all encounters assigned to a doctor."""
    with get_connection(read_only=True) as conn:
        conn.row_factory = lambda cursor, row: {
            "encounter_number": row[0],
            "patient_age": row[1],
            "patient_gender": row[2],
            "los": row[3],
            "review_completed": row[4] == 1,
            "doctor_id": row[5],
        }
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                r.encounter_number,
                r.patient_age,
                r.patient_gender,
                r.LOS,
                r.review_completed,
                d.id as doctor_id
            FROM reviews_to_complete r
            JOIN doctors d ON r.doctor_id = d.id
            WHERE d.id = ?
            ORDER BY r.LOS ASC, r.encounter_number
            """,
            (doctor_id,),
        )
        return cursor.fetchall()


def _get_incidental_counts_for_doctor(doctor_id: int) -> dict[int, int]:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT encounter_id, COUNT(*)
            FROM incidental_findings
            WHERE doctor_id = ?
            GROUP BY encounter_id
            """,
            (doctor_id,),
        )
        rows = cursor.fetchall()
    return {int(row[0]): int(row[1]) for row in rows}


def _get_note_count(encounter_number: int, cache: dict[int, int]) -> int:
    if encounter_number in cache:
        return cache[encounter_number]
    try:
        docs = load_encounter_documents(encounter_number)
        count = len(docs.clinical_notes)
    except Exception:
        count = 0
    cache[encounter_number] = count
    return count


@router.get("/overview")
async def overview(request: Request, user: dict = Depends(manager)):
    """Display the overview dashboard with assigned encounters."""
    email = user.get("email", "")
    doctor_id = get_doctor_id_by_email(email)

    if not doctor_id:
        return templates.TemplateResponse(
            "overview.html",
            {
                "request": request,
                "user": user,
                "encounters": [],
                "error": f"No doctor record found for email: {email}",
            },
        )

    encounters = get_encounters_for_doctor(doctor_id)
    note_count_cache: dict[int, int] = {}
    incidental_counts = _get_incidental_counts_for_doctor(doctor_id)
    for enc in encounters:
        encounter_number = int(enc.get("encounter_number"))
        enc["note_count"] = _get_note_count(encounter_number, note_count_cache)
        enc["findings_count"] = incidental_counts.get(encounter_number, 0)
    is_admin = is_admin_user(user)
    admin_summary = []
    admin_assignments = []
    admin_activity = []
    if is_admin:
        admin_summary = fetch_admin_summary(exclude_doctor_id=doctor_id)
        admin_assignments = fetch_admin_assignments(exclude_doctor_id=doctor_id)
        for assignment in admin_assignments:
            encounter_number = int(assignment.get("encounter_number"))
            assignment["note_count"] = _get_note_count(encounter_number, note_count_cache)
        admin_activity = fetch_admin_activity(limit=50, exclude_doctor_id=doctor_id)
        assignments_by_doctor: dict[int, list[dict]] = {}
        for assignment in admin_assignments:
            assignments_by_doctor.setdefault(assignment["doctor_id"], []).append(assignment)
        admin_summary = [
            {
                **row,
                "assignments": assignments_by_doctor.get(row["doctor_id"], []),
            }
            for row in admin_summary
        ]

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "user": user,
            "encounters": encounters,
            "example_encounters": EXAMPLE_ENCOUNTER_NUMBERS,
            "is_admin": is_admin,
            "admin_summary": admin_summary,
            "admin_activity": admin_activity,
        },
    )
