"""Authentication manager using fastapi-login."""

from datetime import timedelta
from typing import Optional

import yaml
from fastapi import Request
import bcrypt as bcrypt_lib
from fastapi_login import LoginManager
from fastapi_login.exceptions import InvalidCredentialsException

from eval_v2.config import SECRET_KEY, COOKIE_NAME, COOKIE_EXPIRY_DAYS, CONFIG_YAML_PATH


# Initialize the login manager
manager = LoginManager(
    SECRET_KEY,
    token_url="/login",
    use_cookie=True,
    cookie_name=COOKIE_NAME,
    default_expiry=timedelta(days=COOKIE_EXPIRY_DAYS),
)


def load_credentials() -> dict:
    """Load user credentials from config.yaml."""
    try:
        with open(CONFIG_YAML_PATH) as f:
            config = yaml.safe_load(f) or {}
        return config.get("credentials", {}).get("usernames", {})
    except FileNotFoundError:
        return {}


def get_user(username: str) -> Optional[dict]:
    """Get user data by username."""
    users = load_credentials()
    user_data = users.get(username)
    if user_data:
        return {
            "username": username,
            "email": user_data.get("email", ""),
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "password": user_data.get("password", ""),
        }
    return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        return bcrypt_lib.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


@manager.user_loader()
def load_user(username: str) -> Optional[dict]:
    """User loader callback for fastapi-login."""
    return get_user(username)


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Get current user if logged in, otherwise return None."""
    try:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        user = await manager.get_current_user(token)
        return user
    except Exception:
        return None
