"""Routes for managing clinical note highlights (personal reference)."""

import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List

from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.db_utils import (
    fetch_note_highlights,
    create_note_highlight,
    update_note_highlight,
    delete_note_highlight,
)
from eval_v2.services.example_case import is_example_read_only
from eval_v2.services.admin_access import is_admin_user
from eval_v2.services.activity_log import log_activity

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


def get_doctor_id_by_email(email: str) -> int | None:
    """Look up doctor ID by email address."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
        row = cursor.fetchone()
    return row[0] if row else None


def _get_highlight_encounter_number(highlight_id: int, doctor_id: int) -> int | None:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT encounter_number
            FROM note_highlights
            WHERE highlight_id = ? AND doctor_id = ?
            """,
            (highlight_id, doctor_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


class CreateHighlightRequest(BaseModel):
    encounter_number: int
    note_filename: str
    start_offset: int
    end_offset: int
    selected_text: str
    color: str = "yellow"
    comment: Optional[str] = None


class UpdateHighlightRequest(BaseModel):
    color: Optional[str] = None
    comment: Optional[str] = None


@router.get("")
async def get_highlights(
    encounter_number: int = Query(...),
    note_filename: Optional[str] = Query(None),
    review_doctor_id: Optional[int] = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Get all highlights for an encounter, optionally filtered by note filename."""
    logger.debug(f"GET /api/highlights - encounter={encounter_number}, note={note_filename}, user={user.get('email', 'unknown')}")

    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        logger.error(f"Doctor not found for email: {user.get('email', '')}")
        raise HTTPException(status_code=401, detail="Doctor not found for user")
    if review_doctor_id is not None:
        if not admin_view or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="Admin access required")
        doctor_id = review_doctor_id

    try:
        highlights = fetch_note_highlights(encounter_number, doctor_id, note_filename)
        logger.debug(f"Returned {len(highlights)} highlights")
        return JSONResponse(content={"highlights": highlights})
    except Exception as e:
        logger.error(f"Error fetching highlights: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_highlight(
    request: CreateHighlightRequest,
    user: dict = Depends(manager),
):
    """Create a new highlight on a clinical note."""
    logger.info(f"POST /api/highlights - User: {user.get('email', 'unknown')}")
    logger.debug(f"Request data: encounter={request.encounter_number}, note={request.note_filename}, "
                 f"start={request.start_offset}, end={request.end_offset}, color={request.color}, "
                 f"text_len={len(request.selected_text) if request.selected_text else 0}")

    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        logger.error(f"Doctor not found for email: {user.get('email', '')}")
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    if is_example_read_only(request.encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    logger.debug(f"Doctor ID resolved: {doctor_id}")

    # Validate color
    valid_colors = {"yellow", "green", "blue", "pink", "orange"}
    if request.color not in valid_colors:
        logger.warning(f"Invalid color: {request.color}")
        raise HTTPException(status_code=400, detail=f"Invalid color. Must be one of: {valid_colors}")

    try:
        logger.debug("Calling create_note_highlight...")
        highlight = create_note_highlight(
            encounter_number=request.encounter_number,
            doctor_id=doctor_id,
            note_filename=request.note_filename,
            start_offset=request.start_offset,
            end_offset=request.end_offset,
            selected_text=request.selected_text,
            color=request.color,
            comment=request.comment,
        )
        log_activity(
            "highlight_created",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=request.encounter_number,
            details={
                "highlight_id": highlight.get("highlight_id"),
                "color": request.color,
            },
        )
        logger.info(f"Highlight created successfully: id={highlight.get('highlight_id', 'unknown')}")
        return JSONResponse(content={"highlight": highlight}, status_code=201)
    except Exception as e:
        logger.error(f"Error creating highlight: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{highlight_id}")
async def update_highlight(
    highlight_id: int,
    request: UpdateHighlightRequest,
    user: dict = Depends(manager),
):
    """Update a highlight's color or comment."""
    logger.info(f"PATCH /api/highlights/{highlight_id} - User: {user.get('email', 'unknown')}")
    logger.debug(f"Update data: color={request.color}, comment={request.comment}")

    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        logger.error(f"Doctor not found for email: {user.get('email', '')}")
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    encounter_number = _get_highlight_encounter_number(highlight_id, doctor_id)
    if encounter_number is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    if is_example_read_only(encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    # Validate color if provided
    if request.color is not None:
        valid_colors = {"yellow", "green", "blue", "pink", "orange"}
        if request.color not in valid_colors:
            logger.warning(f"Invalid color: {request.color}")
            raise HTTPException(status_code=400, detail=f"Invalid color. Must be one of: {valid_colors}")

    try:
        update_note_highlight(
            highlight_id=highlight_id,
            doctor_id=doctor_id,
            color=request.color,
            comment=request.comment,
        )
        log_activity(
            "highlight_updated",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=encounter_number,
            details={
                "highlight_id": highlight_id,
                "color": request.color,
                "comment_updated": request.comment is not None,
            },
        )
        logger.info(f"Highlight {highlight_id} updated successfully")
        return JSONResponse(content={"success": True})
    except ValueError as e:
        logger.warning(f"Highlight not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating highlight {highlight_id}: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{highlight_id}")
async def delete_highlight(
    highlight_id: int,
    user: dict = Depends(manager),
):
    """Delete a highlight."""
    logger.info(f"DELETE /api/highlights/{highlight_id} - User: {user.get('email', 'unknown')}")

    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        logger.error(f"Doctor not found for email: {user.get('email', '')}")
        raise HTTPException(status_code=401, detail="Doctor not found for user")

    encounter_number = _get_highlight_encounter_number(highlight_id, doctor_id)
    if encounter_number is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    if is_example_read_only(encounter_number):
        raise HTTPException(status_code=403, detail="Example case is read-only")

    try:
        delete_note_highlight(highlight_id, doctor_id)
        log_activity(
            "highlight_deleted",
            doctor_id=doctor_id,
            username=user.get("username"),
            email=user.get("email"),
            encounter_number=encounter_number,
            details={"highlight_id": highlight_id},
        )
        logger.info(f"Highlight {highlight_id} deleted successfully")
        return JSONResponse(content={"success": True})
    except Exception as e:
        logger.error(f"Error deleting highlight {highlight_id}: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
