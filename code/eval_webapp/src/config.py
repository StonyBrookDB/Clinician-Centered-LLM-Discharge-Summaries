"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE or export KEY=VALUE lines without overriding env."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


for _env_path in (BASE_DIR.parent / ".env", BASE_DIR / ".env"):
    _load_env_file(_env_path)

# Database
DB_PATH = DATA_DIR / "reviews.db"
DB_KEY = os.environ.get("DB_KEY", "")

# File encryption
FILES_KEY = os.environ.get("FILES_KEY", "")

# Auth settings
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
COOKIE_NAME = "sbmed_auth"
COOKIE_EXPIRY_DAYS = 1

# Config file for user credentials
CONFIG_YAML_PATH = BASE_DIR / "config.yaml"


def is_gating_logic_enabled() -> bool:
    """Return True only when ENABLE_GATING_LOGIC is explicitly set to 1."""
    return os.environ.get("ENABLE_GATING_LOGIC", "").strip() == "1"


def is_highlights_enabled() -> bool:
    """Return True only when ENABLE_HIGHLIGHTS is explicitly set to 1."""
    return os.environ.get("ENABLE_HIGHLIGHTS", "").strip() == "1"


def is_first_look_enabled() -> bool:
    """Return True only when FIRST_LOOK_ENABLED is explicitly set to 1."""
    return os.environ.get("FIRST_LOOK_ENABLED", "").strip() == "1"


def is_example_case_enabled() -> bool:
    """Publication builds do not include separate example encounters."""
    return False


def get_db_key() -> str:
    """Return the database encryption key, raising if not set."""
    if not DB_KEY:
        raise RuntimeError("DB_KEY environment variable is not set")
    return DB_KEY


def get_files_key() -> str:
    """Return the file encryption key, raising if not set."""
    if not FILES_KEY:
        raise RuntimeError("FILES_KEY environment variable is not set")
    return FILES_KEY
