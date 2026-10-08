from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_password_context = CryptContext(schemes=["argon2"], deprecated="auto")

# Verified when no account matches, so a missing account takes as long as a wrong password.
_DUMMY_HASH = _password_context.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _password_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_context.verify(password, _DUMMY_HASH)
        return False
    return _password_context.verify(password, password_hash)


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int | None:
    """The user_id in a valid, unexpired token, or None."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
