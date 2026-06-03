"""Utilities for converting RTF content to Markdown/HTML with shared caching."""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from eval_v2.services import file_encryption

_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.1


def _failed_marker_path(md_path: Path) -> Path:
    return Path(f"{md_path}.failed")


def _html_failed_marker_path(md_path: Path) -> Path:
    return Path(f"{md_path}.html.failed")


def _lock_path(md_path: Path) -> Path:
    return Path(f"{md_path}.lock")


@contextmanager
def _file_lock(path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    locked = False
    try:
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    break
                time.sleep(_LOCK_POLL_SECONDS)
        yield locked
    finally:
        if locked:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def convert_rtf_to_markdown(rtf_bytes: bytes) -> Optional[str]:
    """Convert RTF content to Markdown using unrtf | pandoc pipeline.

    Handles embedded images by:
    1. Running unrtf in a temp directory to isolate extracted image files
    2. Stripping <img> tags from the HTML output before pandoc conversion
    3. Cleaning up any image files created by unrtf
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            files_before = set(os.listdir(tmpdir))

            unrtf_result = subprocess.run(
                ["unrtf", "--html"],
                input=rtf_bytes,
                capture_output=True,
                timeout=30,
                cwd=tmpdir,
            )

            if unrtf_result.returncode != 0:
                print(f"unrtf failed: {unrtf_result.stderr.decode('utf-8', errors='ignore')}")
                return None

            html_content = unrtf_result.stdout.decode("utf-8", errors="ignore")
            html_content = re.sub(r"<img[^>]*>", "", html_content, flags=re.IGNORECASE)

            files_after = set(os.listdir(tmpdir))
            new_files = files_after - files_before
            for filename in new_files:
                filepath = os.path.join(tmpdir, filename)
                if os.path.isfile(filepath):
                    try:
                        os.remove(filepath)
                        print(f"Removed unrtf-extracted file: {filename}")
                    except OSError as exc:
                        print(f"Warning: Could not remove {filename}: {exc}")

            pandoc_result = subprocess.run(
                ["pandoc", "-f", "html", "-t", "markdown", "--wrap=none"],
                input=html_content.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )

            if pandoc_result.returncode != 0:
                print(f"pandoc failed: {pandoc_result.stderr.decode('utf-8', errors='ignore')}")
                return None

            return pandoc_result.stdout.decode("utf-8", errors="ignore")

        except subprocess.TimeoutExpired as exc:
            print(f"Conversion timeout: {exc}")
            return None
        except Exception as exc:
            print(f"Conversion error: {exc}")
            return None


def render_markdown_to_html(markdown_text: str) -> Optional[str]:
    """Convert markdown text to HTML using pandoc."""
    try:
        result = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "html"],
            input=markdown_text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"pandoc markdown->html failed: {result.stderr.decode('utf-8', errors='ignore')}")
            return None
        return result.stdout.decode("utf-8", errors="ignore")
    except subprocess.TimeoutExpired as exc:
        print(f"pandoc markdown->html timeout: {exc}")
        return None
    except Exception as exc:
        print(f"Error rendering markdown: {exc}")
        return None


def convert_html_to_markdown(html_text: str) -> Optional[str]:
    """Convert HTML/XHTML content to Markdown using pandoc."""
    try:
        result = subprocess.run(
            ["pandoc", "-f", "html", "-t", "markdown", "--wrap=none"],
            input=html_text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"pandoc html->markdown failed: {result.stderr.decode('utf-8', errors='ignore')}")
            return None
        return result.stdout.decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"Error converting HTML to markdown: {exc}")
        return None


def _looks_like_xhtml(markdown_text: str) -> bool:
    if not markdown_text:
        return False
    sample = markdown_text.lstrip()[:500].lower()
    if "<html" not in sample and "<!doctype html" not in sample:
        return False
    if "xmlns=\"http://www.w3.org/1999/xhtml\"" in sample:
        return True
    return "<body" in sample or "<head" in sample


def _read_markdown(md_path: Path, *, encrypted: bool) -> Optional[str]:
    if not md_path.exists():
        return None
    try:
        if encrypted:
            return file_encryption.get_bytes(md_path).decode("utf-8", errors="ignore")
        return md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        print(f"Error reading existing markdown {md_path}: {exc}")
        return None


def _write_failed_marker(path: Path, reason: str) -> None:
    try:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(f"{timestamp}\n{reason}\n", encoding="utf-8")
    except OSError as exc:
        print(f"Warning: Could not write failed marker {path}: {exc}")


def _write_markdown(md_path: Path, markdown_text: str, *, encrypted: bool) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_handle = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(md_path.parent),
            prefix=f"{md_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_handle = Path(handle.name)
            if encrypted:
                handle.write(file_encryption.encrypt_bytes(markdown_text.encode("utf-8")))
            else:
                handle.write(markdown_text.encode("utf-8"))
        os.replace(tmp_handle, md_path)
    finally:
        if tmp_handle and tmp_handle.exists():
            try:
                tmp_handle.unlink(missing_ok=True)
            except OSError:
                pass


def _wait_for_shared_markdown(
    md_path: Path, failed_path: Path, timeout: float, *, encrypted: bool
) -> Optional[str]:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if md_path.exists():
            return _read_markdown(md_path, encrypted=encrypted)
        if failed_path.exists():
            return None
        time.sleep(_LOCK_POLL_SECONDS)
    return None


def get_or_create_markdown(
    rtf_path: Path,
    md_path: Path,
    *,
    encrypted: bool = True,
    allow_generate: bool = True,
) -> Optional[str]:
    """Get existing Markdown file or create from RTF. Returns markdown text."""
    markdown_text = _read_markdown(md_path, encrypted=encrypted)
    if markdown_text is not None:
        if _looks_like_xhtml(markdown_text):
            lock_path = _lock_path(md_path)
            with _file_lock(lock_path) as locked:
                if locked:
                    markdown_text = _read_markdown(md_path, encrypted=encrypted) or markdown_text
                    if _looks_like_xhtml(markdown_text):
                        normalized = convert_html_to_markdown(markdown_text)
                        if normalized:
                            _write_markdown(md_path, normalized, encrypted=encrypted)
                            markdown_text = normalized
        return markdown_text

    failed_path = _failed_marker_path(md_path)
    if failed_path.exists():
        return None

    if not allow_generate:
        return None

    if not rtf_path.exists():
        print(f"RTF file not found: {rtf_path}")
        return None

    lock_path = _lock_path(md_path)
    with _file_lock(lock_path) as locked:
        if not locked:
            return _wait_for_shared_markdown(
                md_path, failed_path, _LOCK_TIMEOUT_SECONDS, encrypted=encrypted
            )

        markdown_text = _read_markdown(md_path, encrypted=encrypted)
        if markdown_text is not None:
            return markdown_text

        if failed_path.exists():
            return None

        try:
            if encrypted:
                rtf_bytes = file_encryption.get_bytes(rtf_path)
            else:
                rtf_bytes = rtf_path.read_bytes()

            print(f"Converting RTF to markdown: {rtf_path} ({len(rtf_bytes)} bytes)")
            markdown = convert_rtf_to_markdown(rtf_bytes)
            if not markdown:
                print(f"Conversion returned empty result for {rtf_path}")
                _write_failed_marker(failed_path, "conversion_failed")
                return None

            if _looks_like_xhtml(markdown):
                print(f"Markdown output looked like XHTML, reprocessing: {rtf_path}")
                normalized = convert_html_to_markdown(markdown)
                if normalized:
                    markdown = normalized

            print(f"Conversion successful, markdown length: {len(markdown)}")
            try:
                _write_markdown(md_path, markdown, encrypted=encrypted)
                if failed_path.exists():
                    failed_path.unlink(missing_ok=True)
            except Exception as exc:
                print(f"Warning: Could not save markdown file: {exc}")
            return markdown
        except Exception as exc:
            print(f"Error in get_or_create_markdown: {exc}")
            _write_failed_marker(failed_path, "exception")
    return None


def is_markdown_failed(md_path: Path) -> bool:
    """Return True if a markdown conversion failure marker exists."""
    return _failed_marker_path(md_path).exists()


def is_html_render_failed(md_path: Path) -> bool:
    """Return True if a markdown-to-HTML render failure marker exists."""
    return _html_failed_marker_path(md_path).exists()


def mark_html_render_failed(md_path: Path, reason: str) -> None:
    """Persist a markdown-to-HTML render failure marker."""
    _write_failed_marker(_html_failed_marker_path(md_path), reason)


def clear_html_render_failed(md_path: Path) -> None:
    """Remove the markdown-to-HTML render failure marker if present."""
    try:
        _html_failed_marker_path(md_path).unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "convert_rtf_to_markdown",
    "get_or_create_markdown",
    "is_markdown_failed",
    "is_html_render_failed",
    "mark_html_render_failed",
    "clear_html_render_failed",
    "render_markdown_to_html",
]
