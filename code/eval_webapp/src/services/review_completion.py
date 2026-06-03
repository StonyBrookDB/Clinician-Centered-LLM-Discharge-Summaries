"""Helpers for computing and persisting review completion status."""

from __future__ import annotations

from dataclasses import dataclass

from eval_v2.services.db_connection import get_connection


BASE_REQUIRED_FIELDS: tuple[str, ...] = (
    "human_quality",
    "human_clarity",
    "human_factuality",
    "human_completeness",
    "ai_quality",
    "ai_clarity",
    "ai_factuality",
    "ai_completeness",
    "overall_preference",
)

PCP_REQUIRED_FIELDS: tuple[str, ...] = (
    "human_easy_understand",
    "human_easy_verbalize",
    "human_easy_follow_up",
    "ai_easy_understand",
    "ai_easy_verbalize",
    "ai_easy_follow_up",
)


@dataclass(frozen=True)
class CompletionResult:
    completed: bool
    is_pcp: bool


def _fetch_review_row(conn, encounter_number: int, doctor_id: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            d.is_pcp,
            r.human_quality,
            r.human_conciseness,
            r.human_readability,
            r.human_clarity,
            r.human_factuality,
            r.human_completeness,
            r.human_easy_understand,
            r.human_easy_verbalize,
            r.human_easy_follow_up,
            r.ai_quality,
            r.ai_conciseness,
            r.ai_readability,
            r.ai_clarity,
            r.ai_factuality,
            r.ai_completeness,
            r.ai_easy_understand,
            r.ai_easy_verbalize,
            r.ai_easy_follow_up,
            r.overall_preference
        FROM reviews_to_complete r
        JOIN doctors d ON r.doctor_id = d.id
        WHERE r.encounter_number = ? AND r.doctor_id = ?
        """,
        (encounter_number, doctor_id),
    )
    row = cursor.fetchone()
    if not row:
        return None

    columns = (
        "is_pcp",
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
    )
    return dict(zip(columns, row, strict=True))


def compute_completion(encounter_number: int, doctor_id: int) -> CompletionResult:
    """Compute whether a review is complete, using the live database values."""
    with get_connection(read_only=True) as conn:
        review_row = _fetch_review_row(conn, encounter_number, doctor_id)
        if not review_row:
            return CompletionResult(completed=False, is_pcp=False)

        is_pcp = review_row["is_pcp"] == 1
        required_fields = BASE_REQUIRED_FIELDS + (PCP_REQUIRED_FIELDS if is_pcp else ())
        ratings_complete = all(review_row[field] != -1 for field in required_fields)

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM incidental_findings
            WHERE encounter_id = ? AND doctor_id = ?
            """,
            (encounter_number, doctor_id),
        )
        incidental_total = int(cursor.fetchone()[0])

        incidental_complete = True
        if incidental_total > 0:
            cursor.execute(
                """
                SELECT COUNT(*) FROM incidental_findings
                WHERE encounter_id = ? AND doctor_id = ?
                  AND (factuality = -1 OR clinical_importance = -1)
                """,
                (encounter_number, doctor_id),
            )
            incidental_incomplete = int(cursor.fetchone()[0])
            incidental_complete = incidental_incomplete == 0

        return CompletionResult(
            completed=bool(ratings_complete and incidental_complete),
            is_pcp=is_pcp,
        )


def recompute_and_persist(encounter_number: int, doctor_id: int) -> CompletionResult:
    """Recompute completion and persist it to `reviews_to_complete.review_completed`."""
    result = compute_completion(encounter_number, doctor_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reviews_to_complete
            SET review_completed = ?
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (1 if result.completed else 0, encounter_number, doctor_id),
        )
        conn.commit()
    return result
