"""Chronological note chunking."""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import NoteChunk

try:
    import tiktoken

    _ENCODING = tiktoken.encoding_for_model("gpt-4o")
except Exception:  # pragma: no cover - exercised only without optional dependency
    _ENCODING = None


def count_tokens(text: str) -> int:
    """Count tokens with tiktoken when available, otherwise approximate."""

    if _ENCODING is not None:
        return len(_ENCODING.encode(str(text)))
    return max(1, len(str(text)) // 4)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stay_day(admission_datetime: str, publish_datetime: str) -> Optional[int]:
    try:
        admission = _parse_datetime(admission_datetime).date()
        published = _parse_datetime(publish_datetime).date()
        return (published - admission).days
    except Exception:
        return None


def create_note_xml(note: sqlite3.Row) -> str:
    """Create model-visible XML for one note using only safe source IDs."""

    return f"""
<note>
  <note_metadata>
    <source_id>{html.escape(str(note["source_id"]))}</source_id>
    <file_name>{html.escape(str(note["source_id"]))}</file_name>
    <note_type>{html.escape(str(note["note_type"]))}</note_type>
    <publish_datetime>{html.escape(str(note["publish_datetime"]))}</publish_datetime>
  </note_metadata>
  <note_text>
{html.escape(str(note["note_text"]))}
  </note_text>
</note>
""".strip()


def _chunk_rows(
    rows: List[sqlite3.Row],
    chunk_size: int,
    admission_datetime: str,
    encounter_id: str,
) -> List[NoteChunk]:
    chunks: List[NoteChunk] = []
    current_text: List[str] = []
    current_tokens = 0
    current_sources: List[str] = []
    current_start: Optional[int] = None
    current_end: Optional[int] = None

    def flush() -> None:
        nonlocal current_text, current_tokens, current_sources, current_start, current_end
        if not current_text:
            return
        chunks.append(
            NoteChunk(
                encounter_id=encounter_id,
                chunk_position=len(chunks),
                chunk_text="\n\n".join(current_text),
                num_tokens=current_tokens,
                num_included_notes=len(current_sources),
                stay_day_start=current_start,
                stay_day_end=current_end,
                source_ids=list(current_sources),
            )
        )
        current_text = []
        current_tokens = 0
        current_sources = []
        current_start = None
        current_end = None

    for row in rows:
        note_text = str(row["note_text"] or "").strip()
        if not note_text:
            continue
        note_xml = create_note_xml(row)
        note_tokens = count_tokens(note_xml)
        day = _stay_day(admission_datetime, str(row["publish_datetime"]))

        if current_text and current_tokens + note_tokens > chunk_size:
            flush()

        if note_tokens > chunk_size:
            chunks.append(
                NoteChunk(
                    encounter_id=encounter_id,
                    chunk_position=len(chunks),
                    chunk_text=note_xml,
                    num_tokens=note_tokens,
                    num_included_notes=1,
                    stay_day_start=day,
                    stay_day_end=day,
                    source_ids=[str(row["source_id"])],
                )
            )
            continue

        current_text.append(note_xml)
        current_tokens += note_tokens
        current_sources.append(str(row["source_id"]))
        if day is not None:
            current_start = day if current_start is None else min(current_start, day)
            current_end = day if current_end is None else max(current_end, day)

    flush()
    return chunks


def build_chunks(
    connection: sqlite3.Connection,
    encounter_id: str,
    chunk_size: int,
    incidental: bool = False,
) -> List[NoteChunk]:
    """Build and persist chunks for one encounter."""

    encounter = connection.execute(
        "SELECT admission_datetime FROM encounters WHERE encounter_id = ?",
        (encounter_id,),
    ).fetchone()
    if encounter is None:
        raise ValueError(f"Unknown encounter_id: {encounter_id}")

    include_column = "include_for_incidental" if incidental else "include_for_summary"
    rows = connection.execute(
        f"""
        SELECT *
        FROM notes
        WHERE encounter_id = ?
          AND {include_column} = 1
          AND is_reference_summary = 0
        ORDER BY publish_datetime, note_id
        """,
        (encounter_id,),
    ).fetchall()
    chunks = _chunk_rows(
        rows,
        chunk_size=chunk_size,
        admission_datetime=str(encounter["admission_datetime"]),
        encounter_id=encounter_id,
    )

    table = "chunked_incidental_notes" if incidental else "chunked_notes"
    connection.execute(f"DELETE FROM {table} WHERE encounter_id = ?", (encounter_id,))
    for chunk in chunks:
        connection.execute(
            f"""
            INSERT INTO {table} (
                encounter_id,
                chunk_position,
                chunk_text,
                num_tokens,
                num_included_notes,
                stay_day_start,
                stay_day_end,
                source_ids_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.encounter_id,
                chunk.chunk_position,
                chunk.chunk_text,
                chunk.num_tokens,
                chunk.num_included_notes,
                chunk.stay_day_start,
                chunk.stay_day_end,
                json.dumps(chunk.source_ids),
            ),
        )
    connection.commit()
    return chunks


def write_chunks_jsonl(path, clinical_chunks: Dict[str, List[NoteChunk]], incidental_chunks: Dict[str, List[NoteChunk]]) -> None:
    """Write all chunk metadata and text to JSONL for inspection."""

    with open(path, "w", encoding="utf-8") as handle:
        for chunk_type, chunks_by_encounter in (
            ("clinical", clinical_chunks),
            ("incidental", incidental_chunks),
        ):
            for encounter_id, chunks in chunks_by_encounter.items():
                for chunk in chunks:
                    payload = {
                        "chunk_type": chunk_type,
                        "encounter_id": encounter_id,
                        "chunk_position": chunk.chunk_position,
                        "num_tokens": chunk.num_tokens,
                        "num_included_notes": chunk.num_included_notes,
                        "stay_day_start": chunk.stay_day_start,
                        "stay_day_end": chunk.stay_day_end,
                        "source_ids": chunk.source_ids,
                        "chunk_text": chunk.chunk_text,
                    }
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
