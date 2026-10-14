import os

import pytest
from argon2 import Type, extract_parameters
from argon2.low_level import hash_secret

from app.core.security import hash_password, password_needs_rehash, verify_password

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


@pytest.mark.parametrize("password_hash", [None, "", "not-a-hash", "$argon2id$v=19$broken"])
def test_missing_or_malformed_hash_never_verifies(password_hash: str | None) -> None:
    assert not verify_password(PASSWORD, password_hash)
