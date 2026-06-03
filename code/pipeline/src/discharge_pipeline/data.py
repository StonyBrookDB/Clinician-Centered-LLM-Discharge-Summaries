"""CSV validation and SQLite import for the public pipeline."""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


REQUIRED_ENCOUNTER_COLUMNS = {"encounter_id", "age", "sex", "admission_datetime"}
REQUIRED_NOTE_COLUMNS = {
    "encounter_id",
    "note_id",
    "note_type",
    "publish_datetime",
    "note_text",
}

TRUE_VALUES = {"1", "true", "t", "yes", "y"}
FALSE_VALUES = {"0", "false", "f", "no", "n"}


def parse_bool(value: Any, default: bool) -> bool:
    """Parse a flexible CSV boolean value."""

    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized == "":
        return default
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def read_csv_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read a CSV file with UTF-8 BOM tolerance."""

    if not path.is_file():
        raise FileNotFoundError(f"Required CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def validate_columns(name: str, fieldnames: Sequence[str], required: Iterable[str]) -> None:
    """Validate that required columns are present."""

    normalized = {field.strip() for field in fieldnames}
    missing = sorted(set(required) - normalized)
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def make_source_id(encounter_id: str, note_id: str) -> str:
    """Create a stable opaque source identifier for citation tags."""

    payload = f"{encounter_id}|{note_id}".encode("utf-8")
    return "src_" + hashlib.sha256(payload).hexdigest()[:16]


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the public pipeline schema."""

    connection.executescript(
        """
        DROP TABLE IF EXISTS encounters;
        DROP TABLE IF EXISTS note_types;
        DROP TABLE IF EXISTS notes;
        DROP TABLE IF EXISTS chunked_notes;
        DROP TABLE IF EXISTS chunked_incidental_notes;

        CREATE TABLE encounters (
            encounter_id TEXT PRIMARY KEY,
            age TEXT NOT NULL,
            sex TEXT NOT NULL,
            admission_datetime TEXT NOT NULL
        );

        CREATE TABLE note_types (
            note_type TEXT PRIMARY KEY,
            include_for_summary INTEGER NOT NULL DEFAULT 1,
            include_for_incidental INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE notes (
            encounter_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            source_id TEXT NOT NULL UNIQUE,
            note_type TEXT NOT NULL,
            publish_datetime TEXT NOT NULL,
            note_text TEXT NOT NULL,
            include_for_summary INTEGER NOT NULL,
            include_for_incidental INTEGER NOT NULL,
            is_reference_summary INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (encounter_id, note_id),
            FOREIGN KEY (encounter_id) REFERENCES encounters(encounter_id)
        );

        CREATE TABLE chunked_notes (
            encounter_id TEXT NOT NULL,
            chunk_position INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            num_tokens INTEGER NOT NULL,
            num_included_notes INTEGER NOT NULL,
            stay_day_start INTEGER,
            stay_day_end INTEGER,
            source_ids_json TEXT NOT NULL,
            PRIMARY KEY (encounter_id, chunk_position)
        );

        CREATE TABLE chunked_incidental_notes (
            encounter_id TEXT NOT NULL,
            chunk_position INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            num_tokens INTEGER NOT NULL,
            num_included_notes INTEGER NOT NULL,
            stay_day_start INTEGER,
            stay_day_end INTEGER,
            source_ids_json TEXT NOT NULL,
            PRIMARY KEY (encounter_id, chunk_position)
        );

        CREATE INDEX idx_notes_encounter_publish
            ON notes(encounter_id, publish_datetime, note_id);
        """
    )


def _load_note_type_flags(input_dir: Path) -> Dict[str, Dict[str, bool]]:
    note_types_path = input_dir / "note_types.csv"
    if not note_types_path.exists():
        return {}

    fieldnames, rows = read_csv_rows(note_types_path)
    validate_columns("note_types.csv", fieldnames, {"note_type"})
    flags: Dict[str, Dict[str, bool]] = {}
    for row in rows:
        note_type = (row.get("note_type") or "").strip()
        if not note_type:
            continue
        flags[note_type] = {
            "include_for_summary": parse_bool(row.get("include_for_summary"), True),
            "include_for_incidental": parse_bool(row.get("include_for_incidental"), False),
        }
    return flags


def import_csv_bundle(input_dir: Path, database_path: Path) -> sqlite3.Connection:
    """Validate and import a CSV bundle into a new SQLite database."""

    input_dir = input_dir.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    encounter_fields, encounter_rows = read_csv_rows(input_dir / "encounters.csv")
    note_fields, note_rows = read_csv_rows(input_dir / "notes.csv")
    validate_columns("encounters.csv", encounter_fields, REQUIRED_ENCOUNTER_COLUMNS)
    validate_columns("notes.csv", note_fields, REQUIRED_NOTE_COLUMNS)

    note_type_flags = _load_note_type_flags(input_dir)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)

    encounter_ids = set()
    for row in encounter_rows:
        encounter_id = (row.get("encounter_id") or "").strip()
        if not encounter_id:
            raise ValueError("encounters.csv contains a blank encounter_id.")
        encounter_ids.add(encounter_id)
        connection.execute(
            """
            INSERT INTO encounters (encounter_id, age, sex, admission_datetime)
            VALUES (?, ?, ?, ?)
            """,
            (
                encounter_id,
                (row.get("age") or "").strip(),
                (row.get("sex") or "").strip(),
                (row.get("admission_datetime") or "").strip(),
            ),
        )

    for note_type, flags in note_type_flags.items():
        connection.execute(
            """
            INSERT INTO note_types
                (note_type, include_for_summary, include_for_incidental)
            VALUES (?, ?, ?)
            """,
            (
                note_type,
                int(flags["include_for_summary"]),
                int(flags["include_for_incidental"]),
            ),
        )

    seen_notes = set()
    for row in note_rows:
        encounter_id = (row.get("encounter_id") or "").strip()
        note_id = (row.get("note_id") or "").strip()
        note_type = (row.get("note_type") or "").strip()
        if encounter_id not in encounter_ids:
            raise ValueError(f"notes.csv references unknown encounter_id: {encounter_id}")
        if not note_id:
            raise ValueError("notes.csv contains a blank note_id.")
        key = (encounter_id, note_id)
        if key in seen_notes:
            raise ValueError(f"Duplicate note key in notes.csv: {encounter_id}/{note_id}")
        seen_notes.add(key)

        defaults = note_type_flags.get(
            note_type,
            {"include_for_summary": True, "include_for_incidental": False},
        )
        is_reference = parse_bool(row.get("is_reference_summary"), False)
        include_for_summary = parse_bool(
            row.get("include_for_summary"),
            defaults["include_for_summary"],
        )
        include_for_incidental = parse_bool(
            row.get("include_for_incidental"),
            defaults["include_for_incidental"],
        )
        if is_reference:
            include_for_summary = False
            include_for_incidental = False

        if note_type not in note_type_flags:
            connection.execute(
                """
                INSERT OR IGNORE INTO note_types
                    (note_type, include_for_summary, include_for_incidental)
                VALUES (?, ?, ?)
                """,
                (note_type, int(defaults["include_for_summary"]), int(defaults["include_for_incidental"])),
            )

        connection.execute(
            """
            INSERT INTO notes (
                encounter_id,
                note_id,
                source_id,
                note_type,
                publish_datetime,
                note_text,
                include_for_summary,
                include_for_incidental,
                is_reference_summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                encounter_id,
                note_id,
                make_source_id(encounter_id, note_id),
                note_type,
                (row.get("publish_datetime") or "").strip(),
                row.get("note_text") or "",
                int(include_for_summary),
                int(include_for_incidental),
                int(is_reference),
            ),
        )

    connection.commit()
    return connection


def list_encounter_ids(connection: sqlite3.Connection) -> List[str]:
    rows = connection.execute(
        "SELECT encounter_id FROM encounters ORDER BY encounter_id"
    ).fetchall()
    return [str(row["encounter_id"]) for row in rows]


def load_source_metadata(connection: sqlite3.Connection, encounter_id: str) -> Dict[str, Dict[str, Any]]:
    """Return public citation metadata keyed by source_id."""

    rows = connection.execute(
        """
        SELECT source_id, note_id, note_type, publish_datetime
        FROM notes
        WHERE encounter_id = ?
        ORDER BY publish_datetime, note_id
        """,
        (encounter_id,),
    ).fetchall()
    return {
        row["source_id"]: {
            "note_id": row["note_id"],
            "note_type": row["note_type"],
            "publish_datetime": row["publish_datetime"],
        }
        for row in rows
    }
