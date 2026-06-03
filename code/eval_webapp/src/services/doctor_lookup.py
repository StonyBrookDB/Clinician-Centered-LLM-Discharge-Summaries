"""Helpers for mapping authenticated users to doctor records."""

from eval_v2.services.db_connection import get_connection


def get_doctor_id_by_email(email: str) -> int | None:
    """Look up doctor ID by email address."""
    if not email:
        return None
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM doctors WHERE email = ?", (email,))
        row = cursor.fetchone()
        return row[0] if row else None


def get_doctor_id_for_user(user: dict) -> int | None:
    """Resolve doctor ID for the authenticated user."""
    return get_doctor_id_by_email(user.get("email", ""))
