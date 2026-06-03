"""Database helpers for annotation storage."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlcipher3 import dbapi2 as sqlcipher

from eval_v2.services.db_connection import get_connection as get_encrypted_connection

_ANNOTATION_TABLE_COLUMNS = """
    annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_number INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    summary_label TEXT NOT NULL CHECK(summary_label IN ('A','B')),
    summary_part TEXT,
    selection_start INTEGER,
    selection_end INTEGER,
    selected_text TEXT,
    issue_type TEXT NOT NULL CHECK(issue_type IN ('inaccuracy','omission')),
    comment_text TEXT NOT NULL,
    harm_potential INTEGER NOT NULL CHECK(harm_potential BETWEEN 0 AND 7),
    harm_likelihood INTEGER NOT NULL CHECK(harm_likelihood BETWEEN 0 AND 7),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(encounter_number, doctor_id) REFERENCES reviews_to_complete(encounter_number, doctor_id) ON DELETE CASCADE
""".strip()

_ANNOTATION_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS ai_summary_annotations (
    {_ANNOTATION_TABLE_COLUMNS}
)
""".strip()

_ANNOTATION_TABLE_SQL_NO_IF = f"""
CREATE TABLE ai_summary_annotations (
    {_ANNOTATION_TABLE_COLUMNS}
)
""".strip()


@contextmanager
def get_connection() -> Iterable[sqlcipher.Connection]:
    with get_encrypted_connection() as conn:
        conn.row_factory = sqlcipher.Row
        yield conn


def ensure_annotation_schema(conn: sqlcipher.Connection) -> None:
    """Create the annotation table if it does not yet exist."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'ai_summary_annotations'
        """
    )
    row = cursor.fetchone()
    legacy_exists = (
        cursor.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'ai_summary_annotations_legacy'
            """
        ).fetchone()
        is not None
    )

    if row and row["sql"] and "CHECK(issue_type IN ('inaccuracy','omission'))" in row["sql"]:
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            if not legacy_exists:
                conn.execute("ALTER TABLE ai_summary_annotations RENAME TO ai_summary_annotations_legacy")
                legacy_exists = True
            if legacy_exists:
                conn.execute(_ANNOTATION_TABLE_SQL)
                legacy_columns = {
                    col["name"] for col in conn.execute("PRAGMA table_info(ai_summary_annotations_legacy)")
                }
                legacy_summary_part = (
                    "summary_part" if "summary_part" in legacy_columns else "NULL AS summary_part"
                )
                current_count = conn.execute("SELECT COUNT(*) FROM ai_summary_annotations").fetchone()[0]
                if current_count == 0:
                    conn.execute(
                        """
                        INSERT INTO ai_summary_annotations (
                            encounter_number,
                            doctor_id,
                            summary_label,
                            summary_part,
                            selection_start,
                            selection_end,
                            selected_text,
                            issue_type,
                            comment_text,
                            harm_potential,
                            harm_likelihood,
                            status,
                            created_at,
                            updated_at
                        )
                        SELECT
                            encounter_number,
                            doctor_id,
                            summary_label,
                            {legacy_summary_part},
                            selection_start,
                            selection_end,
                            selected_text,
                            issue_type,
                            comment_text,
                            harm_potential,
                            harm_likelihood,
                            status,
                            created_at,
                            updated_at
                        FROM ai_summary_annotations_legacy
                        """.format(legacy_summary_part=legacy_summary_part)
                    )
                conn.execute("DROP TABLE ai_summary_annotations_legacy")
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    cursor.execute(_ANNOTATION_TABLE_SQL)
    columns = {col["name"] for col in cursor.execute("PRAGMA table_info(ai_summary_annotations)")}
    if "summary_part" not in columns:
        cursor.execute("ALTER TABLE ai_summary_annotations ADD COLUMN summary_part TEXT")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_annotations_encounter_doctor
        ON ai_summary_annotations (encounter_number, doctor_id, summary_label)
        """
    )
    conn.commit()


def fetch_annotations(
    encounter_number: int,
    doctor_id: int,
    summary_label: str = "B",
    summary_part: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        ensure_annotation_schema(conn)
        query = """
            SELECT *
            FROM ai_summary_annotations
            WHERE encounter_number = ?
              AND doctor_id = ?
              AND summary_label = ?
        """
        params: list[Any] = [encounter_number, doctor_id, summary_label]
        if summary_part is not None:
            query += " AND summary_part = ?"
            params.append(summary_part)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def create_annotation(
    encounter_number: int,
    doctor_id: int,
    summary_label: str,
    summary_part: Optional[str],
    issue_type: str,
    comment_text: str,
    harm_potential: int,
    harm_likelihood: int,
    *,
    selection_start: Optional[int] = None,
    selection_end: Optional[int] = None,
    selected_text: Optional[str] = None,
) -> Dict[str, Any]:
    timestamp = _utc_iso()
    with get_connection() as conn:
        ensure_annotation_schema(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_summary_annotations (
                encounter_number,
                doctor_id,
                summary_label,
                summary_part,
                selection_start,
                selection_end,
                selected_text,
                issue_type,
                comment_text,
                harm_potential,
                harm_likelihood,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                encounter_number,
                doctor_id,
                summary_label,
                summary_part,
                selection_start,
                selection_end,
                selected_text,
                issue_type,
                comment_text,
                harm_potential,
                harm_likelihood,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        annotation_id = cursor.lastrowid

        row = cursor.execute(
            """
            SELECT *
            FROM ai_summary_annotations
            WHERE annotation_id = ?
            """,
            (annotation_id,),
        ).fetchone()

    return dict(row)


def update_annotation(
    annotation_id: int,
    doctor_id: int,
    *,
    issue_type: str,
    comment_text: str,
    harm_potential: int,
    harm_likelihood: int,
    summary_part: Optional[str] = None,
    selection_start: Optional[int] = None,
    selection_end: Optional[int] = None,
    selected_text: Optional[str] = None,
) -> None:
    timestamp = _utc_iso()
    with get_connection() as conn:
        ensure_annotation_schema(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_summary_annotations
            SET
                summary_part = ?,
                selection_start = ?,
                selection_end = ?,
                selected_text = ?,
                issue_type = ?,
                comment_text = ?,
                harm_potential = ?,
                harm_likelihood = ?,
                updated_at = ?
            WHERE annotation_id = ? AND doctor_id = ?
            """,
            (
                summary_part,
                selection_start,
                selection_end,
                selected_text,
                issue_type,
                comment_text,
                harm_potential,
                harm_likelihood,
                timestamp,
                annotation_id,
                doctor_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Annotation {annotation_id} not found or access denied.")
        conn.commit()


def update_annotation_status(annotation_id: int, doctor_id: int, status: str) -> None:
    if status not in ("open", "resolved"):
        raise ValueError("status must be 'open' or 'resolved'")

    with get_connection() as conn:
        ensure_annotation_schema(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE ai_summary_annotations
            SET status = ?, updated_at = ?
            WHERE annotation_id = ? AND doctor_id = ?
            """,
            (status, _utc_iso(), annotation_id, doctor_id),
        )
        conn.commit()


def delete_annotation(annotation_id: int, doctor_id: int) -> None:
    with get_connection() as conn:
        ensure_annotation_schema(conn)
        conn.execute(
            """
            DELETE FROM ai_summary_annotations
            WHERE annotation_id = ? AND doctor_id = ?
            """,
            (annotation_id, doctor_id),
        )
        conn.commit()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Note Highlights (Personal Reference) ----

_NOTE_HIGHLIGHTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS note_highlights (
    highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_number INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    note_filename TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    selected_text TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'yellow' CHECK(color IN ('yellow', 'green', 'blue', 'pink', 'orange')),
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(encounter_number, doctor_id) REFERENCES reviews_to_complete(encounter_number, doctor_id) ON DELETE CASCADE
)
""".strip()


def ensure_note_highlights_schema(conn: sqlcipher.Connection) -> None:
    """Create the note_highlights table if it does not exist."""
    cursor = conn.cursor()
    cursor.execute(_NOTE_HIGHLIGHTS_TABLE_SQL)
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_note_highlights_encounter_doctor
        ON note_highlights (encounter_number, doctor_id, note_filename)
        """
    )
    conn.commit()


def fetch_note_highlights(
    encounter_number: int, doctor_id: int, note_filename: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch highlights for an encounter/doctor, optionally filtered by note."""
    with get_connection() as conn:
        ensure_note_highlights_schema(conn)
        if note_filename:
            rows = conn.execute(
                """
                SELECT *
                FROM note_highlights
                WHERE encounter_number = ?
                  AND doctor_id = ?
                  AND note_filename = ?
                ORDER BY start_offset ASC
                """,
                (encounter_number, doctor_id, note_filename),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM note_highlights
                WHERE encounter_number = ?
                  AND doctor_id = ?
                ORDER BY note_filename, start_offset ASC
                """,
                (encounter_number, doctor_id),
            ).fetchall()

    return [dict(row) for row in rows]


def create_note_highlight(
    encounter_number: int,
    doctor_id: int,
    note_filename: str,
    start_offset: int,
    end_offset: int,
    selected_text: str,
    color: str = "yellow",
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new highlight on a clinical note."""
    timestamp = _utc_iso()
    with get_connection() as conn:
        ensure_note_highlights_schema(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO note_highlights (
                encounter_number,
                doctor_id,
                note_filename,
                start_offset,
                end_offset,
                selected_text,
                color,
                comment,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                encounter_number,
                doctor_id,
                note_filename,
                start_offset,
                end_offset,
                selected_text,
                color,
                comment,
                timestamp,
            ),
        )
        conn.commit()
        highlight_id = cursor.lastrowid

        row = cursor.execute(
            "SELECT * FROM note_highlights WHERE highlight_id = ?",
            (highlight_id,),
        ).fetchone()

    return dict(row)


def update_note_highlight(
    highlight_id: int,
    doctor_id: int,
    *,
    color: Optional[str] = None,
    comment: Optional[str] = None,
) -> None:
    """Update a highlight's color or comment."""
    with get_connection() as conn:
        ensure_note_highlights_schema(conn)
        cursor = conn.cursor()

        # Build dynamic update
        updates: List[str] = []
        params: List[Any] = []

        if color is not None:
            updates.append("color = ?")
            params.append(color)
        if comment is not None:
            updates.append("comment = ?")
            params.append(comment)

        if not updates:
            return  # Nothing to update

        params.extend([highlight_id, doctor_id])

        cursor.execute(
            f"""
            UPDATE note_highlights
            SET {', '.join(updates)}
            WHERE highlight_id = ? AND doctor_id = ?
            """,
            params,
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Highlight {highlight_id} not found or access denied.")
        conn.commit()


def delete_note_highlight(highlight_id: int, doctor_id: int) -> None:
    """Delete a highlight."""
    with get_connection() as conn:
        ensure_note_highlights_schema(conn)
        conn.execute(
            "DELETE FROM note_highlights WHERE highlight_id = ? AND doctor_id = ?",
            (highlight_id, doctor_id),
        )
        conn.commit()
