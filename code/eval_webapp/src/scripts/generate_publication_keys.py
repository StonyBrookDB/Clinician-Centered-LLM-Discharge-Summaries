"""Generate local encryption keys for the publication demo app."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


KEY_DEFAULTS = {
    "DB_KEY": lambda: secrets.token_urlsafe(48),
    "FILES_KEY": lambda: Fernet.generate_key().decode("ascii"),
    "SECRET_KEY": lambda: secrets.token_urlsafe(48),
}


def _parse_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _line_key(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped or stripped.startswith("#"):
        return None
    key = stripped.split("=", 1)[0].strip()
    return key or None


def _line_value(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped or stripped.startswith("#"):
        return ""
    return stripped.split("=", 1)[1].strip().strip('"').strip("'")


def write_keys(env_path: Path, *, overwrite: bool = False) -> dict[str, str]:
    """Write missing publication keys to a shell-compatible .env file."""
    lines = _parse_env_lines(env_path)
    existing_values = {
        key: _line_value(line)
        for line in lines
        if (key := _line_key(line)) is not None
    }

    generated: dict[str, str] = {}
    new_lines: list[str] = []

    for line in lines:
        key = _line_key(line)
        if key in KEY_DEFAULTS and (overwrite or not _line_value(line)):
            value = KEY_DEFAULTS[key]()
            generated[key] = value
            new_lines.append(f'export {key}="{value}"')
        else:
            new_lines.append(line)

    for key, factory in KEY_DEFAULTS.items():
        if key not in existing_values:
            value = factory()
            generated[key] = value
            new_lines.append(f'export {key}="{value}"')

    env_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local keys for the publication demo app.")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to the .env file to update.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing DB_KEY, FILES_KEY, and SECRET_KEY values.")
    args = parser.parse_args()

    generated = write_keys(args.env, overwrite=args.overwrite)
    if generated:
        print(f"Wrote {len(generated)} key(s) to {args.env}.")
    else:
        print(f"No changes needed; keys already exist in {args.env}.")
    print("Before running the app, source the file in your shell: source .env")


if __name__ == "__main__":
    main()
