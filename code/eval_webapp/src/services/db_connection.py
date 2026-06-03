"""Centralized helpers for establishing SQLCipher-backed database connections."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlcipher3 import dbapi2 as sqlcipher

from eval_v2.config import DB_PATH, CONFIG_YAML_PATH

DEFAULT_DB_PATH = DB_PATH

_DB_KEY_CACHE: Optional[str] = None


class DatabaseKeyError(RuntimeError):
    """Raised when the database encryption key is unavailable or invalid."""


def _load_db_key() -> str:
    """Return the encryption key, preferring the DB_KEY environment variable."""
    global _DB_KEY_CACHE
    if _DB_KEY_CACHE:
        return _DB_KEY_CACHE

    key = os.getenv("DB_KEY")
    if not key and CONFIG_YAML_PATH.exists():
        try:
            import yaml

            config = yaml.safe_load(CONFIG_YAML_PATH.read_text()) or {}
            database_config = config.get("database") or {}
            key = database_config.get("encryption_key")
        except Exception:
            key = None

    if not key:
        raise DatabaseKeyError(
            "Database encryption key missing. Export DB_KEY in the shell before launching the app."
        )

    _DB_KEY_CACHE = str(key)
    return _DB_KEY_CACHE


def connect(
    db_path: Path | str | None = None,
    *,
    read_only: bool = False,
    enable_wal: bool = True,
) -> sqlcipher.Connection:
    """
    Establish a SQLCipher connection to the reviews database.

    Args:
        db_path: Optional override for the database file location.
        read_only: Open the database in read-only mode.
        enable_wal: Enable WAL journaling for improved concurrency when writable.
    """
    key = _load_db_key()
    path = Path(db_path or DEFAULT_DB_PATH).resolve()

    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlcipher.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher.connect(str(path))

    escaped_key = key.replace("'", "''")
    conn.executescript(f"PRAGMA key = '{escaped_key}';")
    conn.execute("PRAGMA cipher_memory_security = ON;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    if enable_wal and not read_only:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

    try:
        conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()
    except sqlcipher.DatabaseError as exc:
        conn.close()
        raise DatabaseKeyError(
            "Unable to open encrypted database with the supplied key. "
            "Verify DB_KEY or migrate existing plaintext databases using the migration script."
        ) from exc

    return conn


@contextmanager
def get_connection(
    db_path: Path | str | None = None,
    *,
    read_only: bool = False,
    enable_wal: bool = True,
) -> Iterator[sqlcipher.Connection]:
    """Context manager wrapper around :func:`connect`."""
    conn = connect(db_path=db_path, read_only=read_only, enable_wal=enable_wal)
    try:
        yield conn
    finally:
        conn.close()


__all__ = [
    "DEFAULT_DB_PATH",
    "DatabaseKeyError",
    "connect",
    "get_connection",
]
