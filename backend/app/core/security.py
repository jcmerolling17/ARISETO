from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

# Argon2id with argon2-cffi's default parameters (Section 4).
_password_hasher = PasswordHasher()

# Verified when no account matches, so a missing account takes as long as a wrong password.
_DUMMY_HASH = _password_hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _verify(_DUMMY_HASH, password)
        return False
    return _verify(password_hash, password)


def password_needs_rehash(password_hash: str) -> bool:
    """True when a stored hash uses parameters other than the current ones."""
    return _password_hasher.check_needs_rehash(password_hash)


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
