"""Helpers for managing the demo-only dummy account and encounter."""

from __future__ import annotations

import csv
import shutil

import bcrypt as bcrypt_lib
import yaml

from eval_v2.config import BASE_DIR, CONFIG_YAML_PATH, DATA_DIR
from eval_v2.services import file_encryption
from eval_v2.services.db_connection import get_connection
from eval_v2.services.example_case import EXAMPLE_ENCOUNTER_NUMBERS


DUMMY_DOCTOR_ID = -1
DUMMY_USERNAME = "test"
DUMMY_PASSWORD = "test"
DUMMY_EMAIL = "test@test.com"
DUMMY_FIRST_NAME = "Demo"
DUMMY_LAST_NAME = "Observer"
DUMMY_ENCOUNTER_NUMBER = -1
DUMMY_FILE_PATH = "dummy_account"

DUMMY_ACCOUNT_ROOT = BASE_DIR / "dummy_account"
DUMMY_ASSETS_DIR = DUMMY_ACCOUNT_ROOT / str(DUMMY_ENCOUNTER_NUMBER)
DUMMY_RAW_DIR = DATA_DIR / "raw" / str(DUMMY_ENCOUNTER_NUMBER)
DUMMY_INCIDENTAL_CSV = DATA_DIR / "incidental_findings.csv"

_REVIEW_RATING_FIELDS = [
    "human_quality",
    "human_conciseness",
    "human_readability",
    "human_clarity",
    "human_factuality",
    "human_completeness",
    "human_easy_understand",
    "human_easy_verbalize",
    "human_easy_follow_up",
    "ai_quality",
    "ai_conciseness",
    "ai_readability",
    "ai_clarity",
    "ai_factuality",
    "ai_completeness",
    "ai_easy_understand",
    "ai_easy_verbalize",
    "ai_easy_follow_up",
    "overall_preference",
]


def is_dummy_encounter(encounter_number: int | str) -> bool:
    try:
        value = int(encounter_number)
    except (TypeError, ValueError):
        return False
    return value == DUMMY_ENCOUNTER_NUMBER


def _load_config() -> dict:
    if CONFIG_YAML_PATH.exists():
        with CONFIG_YAML_PATH.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    else:
        config = {}

    if not isinstance(config.get("credentials"), dict):
        config["credentials"] = {}
    if not isinstance(config["credentials"].get("usernames"), dict):
        config["credentials"]["usernames"] = {}

    return config


def _backup_and_write_config(config: dict) -> None:
    if CONFIG_YAML_PATH.exists():
        backup_path = CONFIG_YAML_PATH.with_suffix(CONFIG_YAML_PATH.suffix + ".bak")
        shutil.copy2(CONFIG_YAML_PATH, backup_path)
        print(f"Backed up existing config to {backup_path}")

    with CONFIG_YAML_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, default_flow_style=False, allow_unicode=True)


def _ensure_dummy_credentials() -> None:
    config = _load_config()
    usernames = config["credentials"]["usernames"]
    existing = usernames.get(DUMMY_USERNAME, {})

    if existing:
        existing_email = (existing.get("email") or "").strip()
        if existing_email and existing_email.lower() != DUMMY_EMAIL:
            raise ValueError(
                f"Credentials for '{DUMMY_USERNAME}' already exist with email {existing_email}. "
                "Refusing to overwrite."
            )

    password_hash = existing.get("password")
    needs_hash = True
    if password_hash:
        try:
            needs_hash = not bcrypt_lib.checkpw(
                DUMMY_PASSWORD.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except Exception:
            needs_hash = True
    if needs_hash:
        password_hash = bcrypt_lib.hashpw(
            DUMMY_PASSWORD.encode("utf-8"),
            bcrypt_lib.gensalt(),
        ).decode("utf-8")

    usernames[DUMMY_USERNAME] = {
        "email": DUMMY_EMAIL,
        "first_name": DUMMY_FIRST_NAME,
        "last_name": DUMMY_LAST_NAME,
        "password": password_hash,
    }

    _backup_and_write_config(config)


def _ensure_dummy_assets_installed() -> None:
    if DUMMY_ENCOUNTER_NUMBER in EXAMPLE_ENCOUNTER_NUMBERS:
        raise ValueError(
            f"Dummy encounter number {DUMMY_ENCOUNTER_NUMBER} collides with example case."
        )

    source_dir = DUMMY_ASSETS_DIR
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Dummy encounter assets not found at {source_dir}. "
            "Create fabricated assets before installing the dummy account."
        )

    if DUMMY_RAW_DIR.exists():
        shutil.rmtree(DUMMY_RAW_DIR, ignore_errors=True)
    DUMMY_RAW_DIR.mkdir(parents=True, exist_ok=True)

    for path in source_dir.rglob("*"):
        if path.is_dir():
            continue

        relative = path.relative_to(source_dir)
        dest_path = DUMMY_RAW_DIR / relative
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            plaintext = file_encryption.decrypt_bytes(path.read_bytes())
            dest_path.write_bytes(file_encryption.encrypt_bytes(plaintext))
        except Exception as exc:
            raise RuntimeError(
                "Dummy assets require FILES_KEY to install. "
                f"Unable to encrypt copied asset {path}."
            ) from exc


def ensure_dummy_doctor(cursor) -> None:
    cursor.execute("SELECT email FROM doctors WHERE id = ?", (DUMMY_DOCTOR_ID,))
    row = cursor.fetchone()
    if row:
        existing_email = (row[0] or "").strip()
        if existing_email and existing_email.lower() != DUMMY_EMAIL:
            raise ValueError(
                f"Doctor id {DUMMY_DOCTOR_ID} already exists with email {existing_email}. "
                "Refusing to overwrite."
            )
        cursor.execute(
            """
            UPDATE doctors
            SET email = ?, first_name = ?, last_name = ?, is_pcp = 1
            WHERE id = ?
            """,
            (DUMMY_EMAIL, DUMMY_FIRST_NAME, DUMMY_LAST_NAME, DUMMY_DOCTOR_ID),
        )
        return

    cursor.execute(
        """
        INSERT INTO doctors (id, email, first_name, last_name, is_pcp)
        VALUES (?, ?, ?, ?, 1)
        """,
        (DUMMY_DOCTOR_ID, DUMMY_EMAIL, DUMMY_FIRST_NAME, DUMMY_LAST_NAME),
    )


def _load_dummy_incidental_findings() -> list[str]:
    if not DUMMY_INCIDENTAL_CSV.exists():
        return []

    with DUMMY_INCIDENTAL_CSV.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        if "encounter_id" not in reader.fieldnames or "content" not in reader.fieldnames:
            raise ValueError("incidental_findings.csv must include encounter_id and content columns.")

        findings = []
        for row in reader:
            raw_encounter = (row.get("encounter_id") or "").strip()
            if not raw_encounter:
                continue
            if str(raw_encounter) != str(DUMMY_ENCOUNTER_NUMBER):
                continue
            content = (row.get("content") or "").strip()
            if content:
                findings.append(content)
        return findings


def _reset_dummy_review(cursor) -> None:
    ratings_clause = ", ".join(f"{field} = ?" for field in _REVIEW_RATING_FIELDS)
    rating_values = [-1] * len(_REVIEW_RATING_FIELDS)
    cursor.execute(
        f"""
        UPDATE reviews_to_complete
        SET patient_age = ?,
            patient_gender = ?,
            LOS = ?,
            review_completed = 0,
            first_look = ?,
            {ratings_clause},
            overall_preference_comment = ?,
            file_path = ?
        WHERE encounter_number = ? AND doctor_id = ?
        """,
        (
            55,
            "Female",
            3,
            "Human",
            *rating_values,
            "",
            DUMMY_FILE_PATH,
            DUMMY_ENCOUNTER_NUMBER,
            DUMMY_DOCTOR_ID,
        ),
    )


def _insert_dummy_review(cursor) -> None:
    ratings = [-1] * len(_REVIEW_RATING_FIELDS)
    cursor.execute(
        """
        INSERT INTO reviews_to_complete
        (encounter_number, doctor_id, patient_age, patient_gender, LOS, review_completed, first_look,
         human_quality, human_conciseness, human_readability, human_clarity, human_factuality,
         human_completeness,
         human_easy_understand, human_easy_verbalize, human_easy_follow_up,
         ai_quality, ai_conciseness, ai_readability, ai_clarity, ai_factuality, ai_completeness,
         ai_easy_understand, ai_easy_verbalize, ai_easy_follow_up,
         overall_preference, overall_preference_comment, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            DUMMY_ENCOUNTER_NUMBER,
            DUMMY_DOCTOR_ID,
            55,
            "Female",
            3,
            0,
            "Human",
            *ratings,
            "",
            DUMMY_FILE_PATH,
        ),
    )


def install_dummy_account() -> None:
    """Install or reset the demo-only dummy account and encounter."""
    _ensure_dummy_assets_installed()
    _ensure_dummy_credentials()

    incidental_defaults = _load_dummy_incidental_findings()

    with get_connection() as conn:
        cursor = conn.cursor()
        ensure_dummy_doctor(cursor)

        cursor.execute(
            """
            SELECT 1 FROM reviews_to_complete
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (DUMMY_ENCOUNTER_NUMBER, DUMMY_DOCTOR_ID),
        )
        exists = cursor.fetchone() is not None

        if exists:
            _reset_dummy_review(cursor)
        else:
            _insert_dummy_review(cursor)

        cursor.execute(
            """
            DELETE FROM incidental_findings
            WHERE encounter_id = ? AND doctor_id = ?
            """,
            (DUMMY_ENCOUNTER_NUMBER, DUMMY_DOCTOR_ID),
        )
        cursor.execute(
            """
            DELETE FROM note_highlights
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (DUMMY_ENCOUNTER_NUMBER, DUMMY_DOCTOR_ID),
        )
        cursor.execute(
            """
            DELETE FROM ai_summary_annotations
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (DUMMY_ENCOUNTER_NUMBER, DUMMY_DOCTOR_ID),
        )

        for content in incidental_defaults:
            cursor.execute(
                """
                INSERT INTO incidental_findings
                (encounter_id, doctor_id, content, factuality, clinical_importance, clinical_importance_comment)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (DUMMY_ENCOUNTER_NUMBER, DUMMY_DOCTOR_ID, content, -1, -1, None),
            )

        conn.commit()

    print("Dummy account installed and ready.")


__all__ = [
    "DUMMY_DOCTOR_ID",
    "DUMMY_USERNAME",
    "DUMMY_PASSWORD",
    "DUMMY_EMAIL",
    "DUMMY_FIRST_NAME",
    "DUMMY_LAST_NAME",
    "DUMMY_ENCOUNTER_NUMBER",
    "DUMMY_FILE_PATH",
    "DUMMY_ACCOUNT_ROOT",
    "DUMMY_ASSETS_DIR",
    "is_dummy_encounter",
    "install_dummy_account",
    "ensure_dummy_doctor",
]
