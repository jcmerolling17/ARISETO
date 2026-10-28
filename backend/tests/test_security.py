import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from argon2 import Type, extract_parameters
from argon2.low_level import hash_secret

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    now_ms,
    password_needs_rehash,
    verify_password,
)

PASSWORD = "secret123"


def argon2id_hash(password: str, *, time_cost: int, memory_cost: int, parallelism: int) -> str:
    """An encoded Argon2id hash with the given parameters (16-byte salt, 32-byte hash)."""
    return hash_secret(
        password.encode(),
        os.urandom(16),
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        type=Type.ID,
    ).decode()


def passlib_style_hash(password: str) -> str:
    """The format passlib 1.7.4 stored before Phase 5: Argon2id v=19, m=65536, t=3, p=4."""
    return argon2id_hash(password, time_cost=3, memory_cost=65536, parallelism=4)


def older_parameters_hash(password: str) -> str:
    """A valid Argon2id hash with weaker parameters than the current ones."""
    return argon2id_hash(password, time_cost=2, memory_cost=512, parallelism=2)


def test_hash_password_is_argon2id_and_never_the_plaintext() -> None:
    password_hash = hash_password(PASSWORD)

    assert password_hash.startswith("$argon2id$v=19$")
    assert PASSWORD not in password_hash
    assert extract_parameters(password_hash).type == Type.ID
    assert hash_password(PASSWORD) != password_hash  # a fresh salt every time


def test_hash_password_verifies_and_rejects_a_wrong_password() -> None:
    password_hash = hash_password(PASSWORD)

    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong-password", password_hash)
    assert not verify_password("", password_hash)


def test_passlib_style_hash_still_verifies_without_rehash() -> None:
    old_hash = passlib_style_hash(PASSWORD)

    assert verify_password(PASSWORD, old_hash)
    assert not verify_password("wrong-password", old_hash)
    assert not password_needs_rehash(old_hash)


def test_older_parameters_hash_verifies_and_needs_rehash() -> None:
    old_hash = older_parameters_hash(PASSWORD)

    assert verify_password(PASSWORD, old_hash)
    assert not verify_password("wrong-password", old_hash)
    assert password_needs_rehash(old_hash)


def test_current_hash_does_not_need_rehash() -> None:
    assert not password_needs_rehash(hash_password(PASSWORD))


def test_token_keeps_its_issue_time_to_the_millisecond() -> None:
    issued_at = now_ms()

    token = decode_access_token(create_access_token(7, "member", issued_at=issued_at))

    assert token.user_id == 7
    assert not token.predates(issued_at)
    assert token.predates(issued_at + timedelta(milliseconds=1))
    assert not token.predates(issued_at - timedelta(milliseconds=1))
    assert not token.predates(None)


def test_token_with_a_whole_second_iat_still_decodes() -> None:
    """Tokens issued before Phase 6 carry iat in whole seconds."""
    settings = get_settings()
    issued_at = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    legacy = jwt.encode(
        {"sub": "7", "role": "member", "iat": issued_at, "exp": datetime.now(UTC) + timedelta(1)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    token = decode_access_token(legacy)

    assert token.user_id == 7
    assert token.predates(issued_at + timedelta(milliseconds=1))


def test_token_without_iat_is_refused() -> None:
    settings = get_settings()
    no_iat = jwt.encode(
        {"sub": "7", "exp": datetime.now(UTC) + timedelta(1)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    assert decode_access_token(no_iat) is None


@pytest.mark.parametrize("password_hash", [None, "", "not-a-hash", "$argon2id$v=19$broken"])
def test_missing_or_malformed_hash_never_verifies(password_hash: str | None) -> None:
    assert not verify_password(PASSWORD, password_hash)
