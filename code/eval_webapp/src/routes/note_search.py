"""Routes for searching clinical note markdown text."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.markdown_renderer import get_or_create_markdown, is_markdown_failed
from eval_v2.services.notes_loader import load_encounter_documents
from eval_v2.services.admin_access import is_admin_user


router = APIRouter(prefix="/api/note-search", tags=["note-search"])

MAX_QUERY_LENGTH = 200
_CACHE_TTL_SECONDS = 600
_CACHE_MAX_ENTRIES = 128


@dataclass
class _CacheEntry:
    timestamp: float
    data: Dict[str, object]


_query_cache: "OrderedDict[Tuple[int, str], _CacheEntry]" = OrderedDict()


def _normalize_query(query: str) -> str:
    return query.casefold().strip()


def _get_cached(encounter_number: int, normalized_query: str) -> Optional[Dict[str, object]]:
    key = (encounter_number, normalized_query)
    entry = _query_cache.get(key)
    if not entry:
        return None
    if time.monotonic() - entry.timestamp > _CACHE_TTL_SECONDS:
        _query_cache.pop(key, None)
        return None
    _query_cache.move_to_end(key)
    return entry.data


def _set_cached(encounter_number: int, normalized_query: str, data: Dict[str, object]) -> None:
    key = (encounter_number, normalized_query)
    _query_cache[key] = _CacheEntry(timestamp=time.monotonic(), data=data)
    _query_cache.move_to_end(key)
    while len(_query_cache) > _CACHE_MAX_ENTRIES:
        _query_cache.popitem(last=False)


def get_doctor_id_by_email(email: str) -> Optional[int]:
    """Look up doctor ID by email address."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
        row = cursor.fetchone()
        return row[0] if row else None


def doctor_assigned_to_encounter(encounter_number: int, doctor_id: int) -> bool:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM reviews_to_complete
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (encounter_number, doctor_id),
        )
        return cursor.fetchone() is not None


@router.get("")
async def search_notes(
    encounter_number: int = Query(...),
    q: str = Query(""),
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Search clinical note markdown for an exact, case-insensitive match."""
    query = (q or "").strip()
    if not query:
        return JSONResponse(
            content={
                "query": "",
                "matched_notes": [],
                "unsearchable_notes": [],
                "match_count_by_note": {},
            }
        )
    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(status_code=400, detail="Query too long")

    doctor_id = get_doctor_id_by_email(user.get("email", ""))
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")
    if review_doctor_id is not None:
        if not admin_view or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="Admin access required")
        doctor_id = review_doctor_id
    if not doctor_assigned_to_encounter(encounter_number, doctor_id):
        raise HTTPException(status_code=403, detail="Encounter not assigned to this reviewer")

    normalized_query = _normalize_query(query)
    cached = _get_cached(encounter_number, normalized_query)
    if cached:
        return JSONResponse(content={**cached, "query": query})

    try:
        encounter_docs = load_encounter_documents(encounter_number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    matched_notes: List[str] = []
    unsearchable_notes: List[str] = []
    match_counts: Dict[str, int] = {}

    for note in encounter_docs.clinical_notes:
        md_path = note.path.with_suffix(".md")
        markdown_text = get_or_create_markdown(note.path, md_path, encrypted=True, allow_generate=True)
        if not markdown_text:
            if is_markdown_failed(md_path):
                unsearchable_notes.append(note.file_name)
            continue

        count = markdown_text.casefold().count(normalized_query)
        if count:
            matched_notes.append(note.file_name)
            match_counts[note.file_name] = count

    payload = {
        "query": query,
        "matched_notes": matched_notes,
        "unsearchable_notes": unsearchable_notes,
        "match_count_by_note": match_counts,
    }
    _set_cached(encounter_number, normalized_query, payload)
    return JSONResponse(content=payload)


__all__ = ["router"]
