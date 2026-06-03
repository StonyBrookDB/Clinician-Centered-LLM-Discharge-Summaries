"""Create a clean, demo-only database for the publication webapp."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from eval_v2.config import BASE_DIR, DATA_DIR
from eval_v2.services.db_connection import DatabaseKeyError, get_connection
from eval_v2.services.dummy_account import (
    DUMMY_DOCTOR_ID,
    DUMMY_EMAIL,
    DUMMY_ENCOUNTER_NUMBER,
    DUMMY_FILE_PATH,
    DUMMY_PASSWORD,
    DUMMY_USERNAME,
    install_dummy_account,
)


PUBLICATION_MARKER = BASE_DIR / "PUBLICATION_BUILD"

DEMO_DOCTOR_ROWS = [
    {
        "doctor_id": str(DUMMY_DOCTOR_ID),
        "email": DUMMY_EMAIL,
        "first_name": "Demo",
        "last_name": "Observer",
        "is_pcp": "1",
    }
]

DEMO_REVIEW_ROWS = [
    {
        "encounter_number": str(DUMMY_ENCOUNTER_NUMBER),
        "doctor_id": str(DUMMY_DOCTOR_ID),
        "patient_age": "55",
        "patient_gender": "Female",
        "LOS": "3",
        "file_path": DUMMY_FILE_PATH,
        "first_look": "Human",
    }
]

DEMO_INCIDENTAL_ROWS = [
    {
        "encounter_id": str(DUMMY_ENCOUNTER_NUMBER),
        "content": "A small pulmonary nodule is described in the fabricated radiology note.",
    },
    {
        "encounter_id": str(DUMMY_ENCOUNTER_NUMBER),
        "content": "Mild hepatic steatosis is mentioned in the fabricated imaging report.",
    },
]


def _require_keys() -> None:
    missing = [name for name in ("DB_KEY", "FILES_KEY", "SECRET_KEY") if not os.getenv(name)]
    if not missing:
        return
    missing_text = ", ".join(missing)
    raise RuntimeError(
        f"Missing required environment variable(s): {missing_text}.\n"
        "Run: python -m eval_v2.scripts.generate_publication_keys --env .env\n"
        "Then run: source .env"
    )


def _remove_existing_database() -> None:
    for path in (
        DATA_DIR / "reviews.db",
        DATA_DIR / "reviews.db-wal",
        DATA_DIR / "reviews.db-shm",
    ):
        if path.exists():
            path.unlink()


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_demo_seed_csvs() -> None:
    _write_csv(DATA_DIR / "doctor_info.csv", DEMO_DOCTOR_ROWS)
    _write_csv(DATA_DIR / "review_assignments.csv", DEMO_REVIEW_ROWS)
    _write_csv(DATA_DIR / "incidental_findings.csv", DEMO_INCIDENTAL_ROWS)


def _create_schema() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                is_pcp INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE reviews_to_complete (
                encounter_number INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                patient_age INTEGER NOT NULL,
                patient_gender TEXT NOT NULL,
                LOS INTEGER NOT NULL,
                review_completed BOOLEAN NOT NULL DEFAULT 0,
                first_look TEXT NOT NULL,
                human_quality INTEGER NOT NULL DEFAULT -1,
                human_conciseness INTEGER NOT NULL DEFAULT -1,
                human_readability INTEGER NOT NULL DEFAULT -1,
                human_clarity INTEGER NOT NULL DEFAULT -1,
                human_factuality INTEGER NOT NULL DEFAULT -1,
                human_completeness INTEGER NOT NULL DEFAULT -1,
                human_easy_understand INTEGER NOT NULL DEFAULT -1,
                human_easy_verbalize INTEGER NOT NULL DEFAULT -1,
                human_easy_follow_up INTEGER NOT NULL DEFAULT -1,
                ai_quality INTEGER NOT NULL DEFAULT -1,
                ai_conciseness INTEGER NOT NULL DEFAULT -1,
                ai_readability INTEGER NOT NULL DEFAULT -1,
                ai_clarity INTEGER NOT NULL DEFAULT -1,
                ai_factuality INTEGER NOT NULL DEFAULT -1,
                ai_completeness INTEGER NOT NULL DEFAULT -1,
                ai_easy_understand INTEGER NOT NULL DEFAULT -1,
                ai_easy_verbalize INTEGER NOT NULL DEFAULT -1,
                ai_easy_follow_up INTEGER NOT NULL DEFAULT -1,
                overall_preference INTEGER CHECK (overall_preference IN (-1, 0, 1)) DEFAULT -1,
                overall_preference_comment TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL,
                PRIMARY KEY (encounter_number, doctor_id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE incidental_findings (
                if_id INTEGER PRIMARY KEY AUTOINCREMENT,
                encounter_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                factuality INTEGER CHECK (factuality IN (-1, 0, 1, 2)) DEFAULT -1,
                clinical_importance INTEGER CHECK (clinical_importance IN (-1, 0, 1, 2)) DEFAULT -1,
                clinical_importance_comment TEXT,
                FOREIGN KEY (encounter_id, doctor_id) REFERENCES reviews_to_complete(encounter_number, doctor_id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE ai_summary_annotations (
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
                FOREIGN KEY (encounter_number, doctor_id) REFERENCES reviews_to_complete(encounter_number, doctor_id) ON DELETE CASCADE,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_annotations_encounter_doctor
            ON ai_summary_annotations (encounter_number, doctor_id, summary_label)
            """
        )
        cursor.execute(
            """
            CREATE TABLE note_highlights (
                highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
                encounter_number INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                note_filename TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                selected_text TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#ffff00',
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (encounter_number, doctor_id) REFERENCES reviews_to_complete(encounter_number, doctor_id) ON DELETE CASCADE,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_highlights_encounter_doctor_note
            ON note_highlights (encounter_number, doctor_id, note_filename)
            """
        )
        cursor.execute(
            """
            CREATE TABLE review_activity_log (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id INTEGER,
                username TEXT,
                email TEXT,
                encounter_number INTEGER,
                action_type TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_review_activity_created_at
            ON review_activity_log (created_at DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX idx_review_activity_doctor_id
            ON review_activity_log (doctor_id)
            """
        )
        conn.commit()


def setup_publication_demo(*, allow_non_publication_root: bool = False) -> None:
    if not PUBLICATION_MARKER.exists() and not allow_non_publication_root:
        raise RuntimeError(
            "This setup script is intended for the generated publication_webapp export. "
            "Refusing to reset this checkout without --allow-non-publication-root."
        )
    _require_keys()
    _remove_existing_database()
    _write_demo_seed_csvs()
    try:
        _create_schema()
    except DatabaseKeyError as exc:
        raise RuntimeError(f"Could not create encrypted database: {exc}") from exc
    install_dummy_account()
    print("")
    print("Publication demo setup complete.")
    print(f"Demo login: {DUMMY_USERNAME} / {DUMMY_PASSWORD}")
    print("Run the app with: ENABLE_HIGHLIGHTS=1 python -m uvicorn eval_v2.main:app --reload --port 8000")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create/reset the publication demo database.")
    parser.add_argument(
        "--allow-non-publication-root",
        action="store_true",
        help="Allow running outside a generated publication export. This can delete eval_v2/data/reviews.db.",
    )
    args = parser.parse_args()
    setup_publication_demo(allow_non_publication_root=args.allow_non_publication_root)


if __name__ == "__main__":
    main()
