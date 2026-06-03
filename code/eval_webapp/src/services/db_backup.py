"""Automatic backups for the encrypted SQLCipher database."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pwd
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from eval_v2.config import DB_PATH
from eval_v2.services import db_connection
from eval_v2.services.db_connection import DatabaseKeyError


logger = logging.getLogger(__name__)

_TIMESTAMP_RE = re.compile(r"^\d{8}_\d{6}Z?$")
_MARKER_FILENAME = ".sbmed_backup"
_DB_FILENAME = "reviews.db"

_BACKUP_TASK_NAME = "db_backup_loop"


def _resolve_tosborne2_home() -> Path:
    try:
        return Path(pwd.getpwnam("tosborne2").pw_dir)
    except KeyError:
        logger.warning("User 'tosborne2' not found; falling back to /home/tosborne2.")
        return Path("/home/tosborne2")


def _resolve_backup_root() -> Path:
    base_home = _resolve_tosborne2_home()
    default_root = base_home / "database_backups"

    env_root = os.getenv("DB_BACKUP_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser()
        try:
            env_resolved = env_path.resolve()
            base_resolved = base_home.resolve()
        except OSError:
            env_resolved = env_path
            base_resolved = base_home

        if str(env_resolved).startswith(f"{base_resolved}{os.sep}"):
            return env_resolved

        logger.warning(
            "Ignoring DB_BACKUP_ROOT outside /home/tosborne2: %s",
            env_path,
        )

    return default_root


def _ensure_backup_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(root, 0o700)
    _maybe_chown_to_tosborne2(root)


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        logger.debug("Could not chmod %s to %s", path, oct(mode))


def _maybe_chown_to_tosborne2(path: Path) -> None:
    try:
        if os.geteuid() != 0:
            return
    except AttributeError:
        return

    try:
        user = pwd.getpwnam("tosborne2")
    except KeyError:
        return

    try:
        os.chown(path, user.pw_uid, user.pw_gid)
    except OSError:
        logger.warning("Unable to chown %s to tosborne2", path)


def _backup_enabled() -> bool:
    value = os.getenv("DB_BACKUP_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _backup_interval_seconds() -> int:
    value = os.getenv("DB_BACKUP_INTERVAL_SECONDS", "3600").strip()
    try:
        interval = int(value)
    except ValueError:
        logger.warning("Invalid DB_BACKUP_INTERVAL_SECONDS=%r; using 3600.", value)
        return 3600
    if interval <= 0:
        logger.warning("DB_BACKUP_INTERVAL_SECONDS must be positive; using 3600.")
        return 3600
    return interval


def _parse_int_env(value: Optional[str], *, default: int, name: str) -> int:
    if value is None:
        return default
    value = value.strip()
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Invalid %s=%r; using %d.", name, value, default)
        return default
    return max(parsed, 0)


def _backup_keep_today_count() -> int:
    value = os.getenv("DB_BACKUP_KEEP_TODAY")
    if value is not None:
        return _parse_int_env(value, default=24, name="DB_BACKUP_KEEP_TODAY")

    legacy = os.getenv("DB_BACKUP_KEEP")
    if legacy is not None:
        return _parse_int_env(legacy, default=0, name="DB_BACKUP_KEEP")

    return 24


def _backup_keep_days() -> int:
    value = os.getenv("DB_BACKUP_KEEP_DAYS")
    if value is not None:
        return _parse_int_env(value, default=30, name="DB_BACKUP_KEEP_DAYS")

    legacy = os.getenv("DB_BACKUP_KEEP")
    if legacy is not None:
        return 0

    return 30


def _format_timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%d_%H%M%SZ")


def _ensure_unique_timestamp(root: Path, now: datetime) -> tuple[str, datetime]:
    timestamp = _format_timestamp(now)
    while (root / timestamp).exists() or (root / f"{timestamp}.partial").exists():
        now = now + timedelta(seconds=1)
        timestamp = _format_timestamp(now)
    return timestamp, now


def _try_acquire_lock(lock_path: Path):
    _ensure_backup_root(lock_path.parent)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _release_lock(handle) -> None:
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _remove_sidecar_files(dest_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = dest_path.with_name(dest_path.name + suffix)
        if sidecar.exists() and sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError:
                logger.warning("Unable to remove sidecar file %s", sidecar)


def _safe_cleanup_partial(root: Path, staging_dir: Path) -> None:
    try:
        root_resolved = root.resolve()
        staging_resolved = staging_dir.resolve()
    except OSError:
        return
    if staging_resolved.parent != root_resolved:
        return
    if staging_dir.is_symlink():
        return
    if not staging_dir.name.endswith(".partial"):
        return
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)


def _backup_with_api(dest_path: Path) -> None:
    with db_connection.connect(read_only=True, enable_wal=False) as src_conn:
        with db_connection.connect(db_path=dest_path, enable_wal=False) as dest_conn:
            dest_conn.execute("PRAGMA journal_mode = DELETE;")
            src_conn.backup(dest_conn)


def _backup_with_copy(dest_path: Path) -> None:
    logger.warning("Falling back to filesystem copy for database backup.")
    with db_connection.connect(read_only=False, enable_wal=False) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    shutil.copy2(DB_PATH, dest_path)


def _perform_backup(dest_path: Path) -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database file not found: {DB_PATH}")
    try:
        _backup_with_api(dest_path)
    except AttributeError:
        _backup_with_copy(dest_path)


def create_backup(*, now: Optional[datetime] = None, backup_root: Optional[Path] = None) -> Optional[Path]:
    root = backup_root or _resolve_backup_root()
    _ensure_backup_root(root)

    if now is None:
        now = datetime.now(timezone.utc)

    timestamp, now = _ensure_unique_timestamp(root, now)
    staging_dir = root / f"{timestamp}.partial"
    final_dir = root / timestamp

    try:
        staging_dir.mkdir(mode=0o700, exist_ok=False)
        _chmod_best_effort(staging_dir, 0o700)
        _maybe_chown_to_tosborne2(staging_dir)
    except FileExistsError:
        return None

    dest_path = staging_dir / _DB_FILENAME

    try:
        _perform_backup(dest_path)
    except (DatabaseKeyError, FileNotFoundError) as exc:
        logger.warning("Skipping backup: %s", exc)
        _safe_cleanup_partial(root, staging_dir)
        return None
    except Exception:
        logger.exception("Database backup failed.")
        _safe_cleanup_partial(root, staging_dir)
        return None

    _remove_sidecar_files(dest_path)

    marker_path = staging_dir / _MARKER_FILENAME
    marker_path.write_text("ok", encoding="utf-8")
    _chmod_best_effort(marker_path, 0o600)
    _maybe_chown_to_tosborne2(marker_path)

    _chmod_best_effort(dest_path, 0o600)
    _maybe_chown_to_tosborne2(dest_path)

    staging_dir.replace(final_dir)
    _maybe_chown_to_tosborne2(final_dir)

    logger.info("Database backup created at %s", final_dir)
    return final_dir


def _is_valid_backup_dir(path: Path, root: Path) -> bool:
    try:
        root_resolved = root.resolve()
        path_resolved = path.resolve()
    except OSError:
        return False
    if path_resolved.parent != root_resolved:
        return False
    if path.is_symlink():
        return False
    if not _TIMESTAMP_RE.match(path.name):
        return False
    if not (path / _DB_FILENAME).is_file():
        return False
    if not (path / _MARKER_FILENAME).is_file():
        return False
    return True


def _parse_backup_timestamp(path: Path) -> Optional[datetime]:
    name = path.name
    try:
        if name.endswith("Z"):
            return datetime.strptime(name, "%Y%m%d_%H%M%SZ").replace(tzinfo=timezone.utc)
        return datetime.strptime(name, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune_backups(
    *,
    keep_today: int = 24,
    keep_days: int = 30,
    backup_root: Optional[Path] = None,
) -> list[Path]:
    root = backup_root or _resolve_backup_root()
    if not root.exists():
        return []

    entries: list[tuple[datetime, Path]] = []
    for path in root.iterdir():
        if not path.is_dir() or not _is_valid_backup_dir(path, root):
            continue
        timestamp = _parse_backup_timestamp(path)
        if timestamp is None:
            continue
        entries.append((timestamp, path))

    if not entries:
        return []

    today = datetime.now(timezone.utc).date()
    keep_set: set[Path] = set()

    if keep_today > 0:
        todays = [(ts, path) for ts, path in entries if ts.date() == today]
        todays.sort(key=lambda item: item[0], reverse=True)
        keep_set.update(path for _, path in todays[:keep_today])

    if keep_days > 0:
        cutoff_date = today - timedelta(days=keep_days)
        by_date: dict[datetime.date, tuple[datetime, Path]] = {}
        for ts, path in entries:
            day = ts.date()
            if day >= today or day < cutoff_date:
                continue
            existing = by_date.get(day)
            if not existing or ts > existing[0]:
                by_date[day] = (ts, path)
        keep_set.update(path for _, path in by_date.values())

    deleted: list[Path] = []
    for _, path in entries:
        if path in keep_set:
            continue
        if _is_valid_backup_dir(path, root):
            shutil.rmtree(path)
            deleted.append(path)

    if deleted:
        logger.info("Pruned %d old backups.", len(deleted))
    return deleted


def _run_backup_cycle() -> None:
    if not _backup_enabled():
        return

    root = _resolve_backup_root()
    _ensure_backup_root(root)

    lock_path = root / ".backup.lock"
    handle = _try_acquire_lock(lock_path)
    if handle is None:
        return

    try:
        create_backup(backup_root=root)
        prune_backups(
            keep_today=_backup_keep_today_count(),
            keep_days=_backup_keep_days(),
            backup_root=root,
        )
    finally:
        _release_lock(handle)


async def _backup_loop() -> None:
    interval = _backup_interval_seconds()
    while True:
        try:
            await asyncio.to_thread(_run_backup_cycle)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Database backup cycle failed.")
        await asyncio.sleep(interval)


async def start_periodic_db_backups(app) -> None:
    if not _backup_enabled():
        logger.info("Database backups disabled via DB_BACKUP_ENABLED.")
        return

    task = asyncio.create_task(_backup_loop(), name=_BACKUP_TASK_NAME)
    app.state.db_backup_task = task


async def stop_periodic_db_backups(app) -> None:
    task = getattr(app.state, "db_backup_task", None)
    if not task:
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        app.state.db_backup_task = None
