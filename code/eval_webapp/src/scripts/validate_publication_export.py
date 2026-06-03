"""Conservative checks for a generated publication webapp export."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


FORBIDDEN_PATH_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "example_case",
    "study_results",
    "agent_plans",
    "node_modules",
}

FORBIDDEN_FILENAMES = {
    "config.yaml",
    "config.yaml.bak",
    "generated_user_passwords.csv",
    "reviews.db",
    "reviews.db-wal",
    "reviews.db-shm",
    "example_case_config.json",
}

ALLOWED_EMAILS = {
    "test@test.com",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _repo_root_from_export(export_root: Path) -> Path:
    if (Path.cwd() / "eval_v2").exists() and (Path.cwd() / "agent_plans").exists():
        return Path.cwd()
    parent = export_root.resolve().parent
    if (parent / "eval_v2").exists() and (parent / "agent_plans").exists():
        return parent
    return Path.cwd()


def _load_forbidden_source_tokens(repo_root: Path) -> set[str]:
    tokens: set[str] = set()

    doctor_csv = repo_root / "eval_v2" / "data" / "doctor_info.csv"
    if doctor_csv.exists():
        try:
            with doctor_csv.open("r", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    for key in ("email", "first_name", "last_name"):
                        value = (row.get(key) or "").strip()
                        if value and value.lower() not in ALLOWED_EMAILS and len(value) >= 3:
                            tokens.add(value)
        except OSError:
            pass

    assignments_csv = repo_root / "eval_v2" / "data" / "review_assignments.csv"
    if assignments_csv.exists():
        try:
            with assignments_csv.open("r", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    value = (row.get("encounter_number") or "").strip()
                    if value and value != "-1" and len(value) >= 5:
                        tokens.add(value)
        except OSError:
            pass

    return tokens


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def validate_export(export_root: Path) -> list[str]:
    export_root = export_root.resolve()
    problems: list[str] = []

    if not export_root.exists():
        return [f"Export root does not exist: {export_root}"]
    if not (export_root / "README.md").exists():
        problems.append("Missing README.md")
    if not (export_root / "requirements.txt").exists():
        problems.append("Missing requirements.txt")
    if not (export_root / ".env.example").exists():
        problems.append("Missing .env.example")
    if not (export_root / "eval_v2" / "PUBLICATION_BUILD").exists():
        problems.append("Missing eval_v2/PUBLICATION_BUILD marker")

    repo_root = _repo_root_from_export(export_root)
    source_tokens = _load_forbidden_source_tokens(repo_root)

    raw_dir = export_root / "eval_v2" / "data" / "raw"
    if raw_dir.exists():
        problems.append("Export contains eval_v2/data/raw; runtime demo assets should be generated during setup")

    for path in _iter_files(export_root):
        rel = path.relative_to(export_root)
        parts = set(rel.parts)
        if parts & FORBIDDEN_PATH_PARTS:
            problems.append(f"Forbidden path included: {rel}")
        if path.name in FORBIDDEN_FILENAMES:
            problems.append(f"Forbidden file included: {rel}")
        if path.stat().st_size > 5_000_000:
            problems.append(f"Unexpected large file included: {rel}")

        text = _read_text(path)
        if not text:
            continue
        for email in EMAIL_RE.findall(text):
            if email.lower() not in ALLOWED_EMAILS:
                problems.append(f"Unexpected email address in {rel}: {email}")
        for token in source_tokens:
            if token and token in text:
                problems.append(f"Source-only token appears in {rel}: {token}")

    return sorted(set(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated publication webapp export.")
    parser.add_argument("export_root", type=Path, help="Path to the generated publication export.")
    args = parser.parse_args()

    problems = validate_export(args.export_root)
    if problems:
        print("Publication export validation failed:")
        for problem in problems:
            print(f"- {problem}")
        raise SystemExit(1)
    print(f"Publication export validation passed: {args.export_root}")


if __name__ == "__main__":
    main()
