from dataclasses import dataclass
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


def _epoch_ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def now_ms() -> datetime:
    """The current UTC time cut to whole milliseconds, the precision tokens record."""
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


@dataclass(frozen=True)
class AccessToken:
    user_id: int
    issued_ms: int  # iat in milliseconds since the epoch

    def predates(self, moment: datetime | None) -> bool:
        """True when the token was issued before moment (e.g. the last password change)."""
        return moment is not None and self.issued_ms < _epoch_ms(moment)


def create_access_token(user_id: int, role: str, issued_at: datetime | None = None) -> str:
    """A token whose iat keeps milliseconds, so one issued with a password change is not
    older than that change. Pass issued_at from now_ms() to match a stored timestamp."""
    settings = get_settings()
    issued_at = issued_at or now_ms()
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": _epoch_ms(issued_at) / 1000,
        "exp": issued_at + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessToken | None:
    """The user_id and issue time of a valid, unexpired token, or None."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "iat", "exp"]},
        )
        return AccessToken(int(payload["sub"]), round(float(payload["iat"]) * 1000))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None
