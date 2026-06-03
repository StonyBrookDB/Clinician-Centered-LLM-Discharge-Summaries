"""Utilities for encrypting and decrypting encounter files under data/raw/."""

from __future__ import annotations

import atexit
import base64
import hashlib
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from eval_v2.config import DATA_DIR

RAW_ROOT = DATA_DIR / "raw"
TEMP_ROOT = DATA_DIR.parent / "temp"
FILES_KEY_ENV = "FILES_KEY"
CACHE_TTL_SECONDS = 15 * 60
_ENC_HEADER = b"ENC1\n"

_fernet: Optional[Fernet] = None
_cache_lock = RLock()


@dataclass
class CacheEntry:
    plain_path: Path
    expires_at: float


_pdf_cache: Dict[Path, CacheEntry] = {}


class FileEncryptionError(RuntimeError):
    """Raised when encryption/decryption operations fail."""


def _derive_key(secret: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(secret.encode())
        if len(raw) == 32:
            return base64.urlsafe_b64encode(raw)
    except Exception:
        pass
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _load_key() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet

    key = os.getenv(FILES_KEY_ENV)
    if not key:
        raise FileEncryptionError(
            f"Clinical file encryption key missing. Export {FILES_KEY_ENV} before accessing assets."
        )

    try:
        _fernet = Fernet(_derive_key(key.strip()))
    except Exception as exc:
        raise FileEncryptionError(f"Invalid {FILES_KEY_ENV}: {exc}") from exc
    return _fernet


def ensure_temp_root() -> None:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def _remove_temp(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        return
    parent = path.parent
    while parent != TEMP_ROOT and parent.is_dir():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _clear_cache() -> None:
    with _cache_lock:
        for entry in _pdf_cache.values():
            _remove_temp(entry.plain_path)
        _pdf_cache.clear()


def clear_temp_root() -> None:
    _clear_cache()
    if not TEMP_ROOT.exists():
        return
    for path in sorted(TEMP_ROOT.glob("**/*"), reverse=True):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            else:
                path.rmdir()
        except OSError:
            continue


def _relative_to_raw(path: Path) -> Path:
    try:
        return path.resolve().relative_to(RAW_ROOT.resolve())
    except ValueError as exc:
        raise FileEncryptionError(f"Path {path} is outside the clinical asset root.") from exc


def is_encrypted(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("rb") as fh:
            prefix = fh.read(len(_ENC_HEADER))
        return prefix == _ENC_HEADER
    except OSError:
        return False


def encrypt_bytes(plaintext: bytes) -> bytes:
    return _ENC_HEADER + _load_key().encrypt(plaintext)


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(_ENC_HEADER):
        return data
    token = data[len(_ENC_HEADER):]
    try:
        return _load_key().decrypt(token)
    except InvalidToken as exc:
        raise FileEncryptionError("Unable to decrypt clinical asset; verify FILES_KEY.") from exc


def encrypt_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    if is_encrypted(path):
        return
    plaintext = path.read_bytes()
    path.write_bytes(encrypt_bytes(plaintext))


def decrypt_to_plain(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    data = path.read_bytes()
    plaintext = decrypt_bytes(data)
    if plaintext != data:
        path.write_bytes(plaintext)


def encrypt_directory(directory: Path) -> None:
    for child in directory.rglob("*"):
        if child.is_file() and not child.is_symlink():
            encrypt_file(child)


def decrypt_directory(directory: Path) -> None:
    for child in directory.rglob("*"):
        if child.is_file() and not child.is_symlink():
            decrypt_to_plain(child)


def _cleanup_expired(now: Optional[float] = None) -> None:
    if now is None:
        now = time.monotonic()
    for key, entry in list(_pdf_cache.items()):
        if entry.expires_at <= now or not entry.plain_path.exists():
            _remove_temp(entry.plain_path)
            del _pdf_cache[key]


def _create_temp_plain(path: Path) -> Path:
    ensure_temp_root()
    plaintext = decrypt_bytes(path.read_bytes())
    relative = _relative_to_raw(path)
    dest_dir = TEMP_ROOT / relative.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Preserve the original extension so tools like LibreOffice output correct filenames
    stem = relative.stem
    suffix = relative.suffix or ""
    with tempfile.NamedTemporaryFile(
        dir=dest_dir,
        prefix=f"{stem}_",
        suffix=suffix,
        delete=False,
    ) as tmp:
        tmp.write(plaintext)
        temp_path = Path(tmp.name)
    return temp_path


def ensure_pdf_plain(path: Path) -> Path:
    if not is_encrypted(path):
        return path

    with _cache_lock:
        now = time.monotonic()
        _cleanup_expired(now)
        entry = _pdf_cache.get(path.resolve())
        if entry and entry.plain_path.exists():
            entry.expires_at = now + CACHE_TTL_SECONDS
            return entry.plain_path

        temp_path = _create_temp_plain(path)
        _pdf_cache[path.resolve()] = CacheEntry(temp_path, now + CACHE_TTL_SECONDS)
        return temp_path


@contextmanager
def temporary_plain_file(path: Path):
    if not is_encrypted(path):
        yield path
        return
    temp_path = _create_temp_plain(path)
    try:
        yield temp_path
    finally:
        _remove_temp(temp_path)


def get_bytes(path: Path) -> bytes:
    return decrypt_bytes(path.read_bytes())


def batch_preload_pdfs(encounter_dir: Path) -> None:
    if not encounter_dir.exists():
        return
    for pdf in encounter_dir.rglob("*.pdf"):
        if pdf.is_file():
            try:
                ensure_pdf_plain(pdf)
            except FileEncryptionError:
                continue


atexit.register(clear_temp_root)
