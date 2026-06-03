"""Routes for managing summary annotations (formal review)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List

from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.db_utils import (
    fetch_annotations,
    create_annotation,
    ensure_annotation_schema,
    update_annotation,
    update_annotation_status,
    delete_annotation,
)
from eval_v2.services.example_case import is_example_read_only
from eval_v2.services.admin_access import is_admin_user
from eval_v2.services.activity_log import log_activity

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


def get_doctor_id_by_email(email: str) -> int | None:
    """Look up doctor ID by email address."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
        row = cursor.fetchone()
    return row[0] if row else None


def _get_annotation_encounter_number(annotation_id: int, doctor_id: int) -> int | None:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT encounter_number
            FROM ai_summary_annotations
            WHERE annotation_id = ? AND doctor_id = ?
            """,
            (annotation_id, doctor_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


class CreateAnnotationRequest(BaseModel):
    encounter_number: int
    summary_label: str = "B"
    summary_part: Optional[str] = None
    issue_type: str  # 'inaccuracy', 'omission'
    comment_text: str
    harm_potential: int  # 0-7
    harm_likelihood: int  # 0-7
    selection_start: Optional[int] = None
    selection_end: Optional[int] = None
    selected_text: Optional[str] = None


class UpdateAnnotationRequest(BaseModel):
    summary_part: Optional[str] = None
    issue_type: Optional[str] = None
    comment_text: Optional[str] = None
    harm_potential: Optional[int] = None
    harm_likelihood: Optional[int] = None
    selection_start: Optional[int] = None
    selection_end: Optional[int] = None
    selected_text: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: str  # 'open' or 'resolved'


@router.get("")
async def get_annotations(
    encounter_number: int = Query(...),
    summary_label: str = Query("B"),
    summary_part: Optional[str] = Query(None),
    review_doctor_id: Optional[int] = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Get all annotations for an encounter/summary."""
    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")
    if review_doctor_id is not None:
        if not admin_view or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="Admin access required")
        doctor_id = review_doctor_id

    annotations = fetch_annotations(encounter_number, doctor_id, summary_label, summary_part)
    return JSONResponse(content={"annotations": annotations})


@router.post("")
async def create_new_annotation(
    request: CreateAnnotationRequest,
    user: dict = Depends(manager),
):
    """Create a new annotation on a summary."""
    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    if is_example_read_only(request.encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    # Validate issue_type
    valid_types = {"inaccuracy", "omission"}
    if request.issue_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid issue_type. Must be one of: {valid_types}"
        )

    # Validate harm scores
    if not (0 <= request.harm_potential <= 7):
        raise HTTPException(status_code=400, detail="harm_potential must be between 0 and 7")
    if not (0 <= request.harm_likelihood <= 7):
        raise HTTPException(status_code=400, detail="harm_likelihood must be between 0 and 7")

    try:
        annotation = create_annotation(
            encounter_number=request.encounter_number,
            doctor_id=doctor_id,
            summary_label=request.summary_label,
            summary_part=request.summary_part,
            issue_type=request.issue_type,
            comment_text=request.comment_text,
            harm_potential=request.harm_potential,
            harm_likelihood=request.harm_likelihood,
            selection_start=request.selection_start,
            selection_end=request.selection_end,
            selected_text=request.selected_text,
        )
        log_activity(
            "annotation_created",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=request.encounter_number,
            details={
                "annotation_id": annotation.get("annotation_id"),
                "issue_type": request.issue_type,
                "summary_label": request.summary_label,
                "summary_part": request.summary_part,
            },
        )
        return JSONResponse(content={"annotation": annotation}, status_code=201)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{annotation_id}")
async def update_existing_annotation(
    annotation_id: int,
    request: UpdateAnnotationRequest,
    user: dict = Depends(manager),
):
    """Update an annotation."""
    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    encounter_number = _get_annotation_encounter_number(annotation_id, doctor_id)
    if encounter_number is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if is_example_read_only(encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    # Validate issue_type if provided
    if request.issue_type is not None:
        valid_types = {"inaccuracy", "omission"}
        if request.issue_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid issue_type. Must be one of: {valid_types}"
            )

    # Validate harm scores if provided
    if request.harm_potential is not None and not (0 <= request.harm_potential <= 7):
        raise HTTPException(status_code=400, detail="harm_potential must be between 0 and 7")
    if request.harm_likelihood is not None and not (0 <= request.harm_likelihood <= 7):
        raise HTTPException(status_code=400, detail="harm_likelihood must be between 0 and 7")

    try:
        # Get current annotation to fill in missing fields
        with get_connection() as conn:
            ensure_annotation_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    summary_part,
                    issue_type,
                    comment_text,
                    harm_potential,
                    harm_likelihood,
                    selection_start,
                    selection_end,
                    selected_text
                FROM ai_summary_annotations
                WHERE annotation_id = ? AND doctor_id = ?
                """,
                (annotation_id, doctor_id),
            )
            row = cursor.fetchone()

        current = None
        if row:
            current = {
                "summary_part": row[0],
                "issue_type": row[1],
                "comment_text": row[2],
                "harm_potential": row[3],
                "harm_likelihood": row[4],
                "selection_start": row[5],
                "selection_end": row[6],
                "selected_text": row[7],
            }

        if not current:
            raise HTTPException(status_code=404, detail="Annotation not found")

        update_annotation(
            annotation_id=annotation_id,
            doctor_id=doctor_id,
            summary_part=request.summary_part if request.summary_part is not None else current.get("summary_part"),
            issue_type=request.issue_type or current['issue_type'],
            comment_text=request.comment_text if request.comment_text is not None else current['comment_text'],
            harm_potential=request.harm_potential if request.harm_potential is not None else current['harm_potential'],
            harm_likelihood=request.harm_likelihood if request.harm_likelihood is not None else current['harm_likelihood'],
            selection_start=request.selection_start if request.selection_start is not None else current.get('selection_start'),
            selection_end=request.selection_end if request.selection_end is not None else current.get('selection_end'),
            selected_text=request.selected_text if request.selected_text is not None else current.get('selected_text'),
        )
        log_activity(
            "annotation_updated",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=encounter_number,
            details={
                "annotation_id": annotation_id,
                "issue_type": request.issue_type or current["issue_type"],
                "summary_part": request.summary_part if request.summary_part is not None else current.get("summary_part"),
            },
        )
        return JSONResponse(content={"success": True})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{annotation_id}/status")
async def update_status(
    annotation_id: int,
    request: UpdateStatusRequest,
    user: dict = Depends(manager),
):
    """Update an annotation's status (open/resolved)."""
    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    encounter_number = _get_annotation_encounter_number(annotation_id, doctor_id)
    if encounter_number is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if is_example_read_only(encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    try:
        update_annotation_status(annotation_id, doctor_id, request.status)
        log_activity(
            "annotation_status_updated",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=encounter_number,
            details={
                "annotation_id": annotation_id,
                "status": request.status,
            },
        )
        return JSONResponse(content={"success": True})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{annotation_id}")
async def delete_existing_annotation(
    annotation_id: int,
    user: dict = Depends(manager),
):
    """Delete an annotation."""
    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    encounter_number = _get_annotation_encounter_number(annotation_id, doctor_id)
    if encounter_number is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if is_example_read_only(encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    try:
        delete_annotation(annotation_id, doctor_id)
        log_activity(
            "annotation_deleted",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=encounter_number,
            details={"annotation_id": annotation_id},
        )
        return JSONResponse(content={"success": True})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
