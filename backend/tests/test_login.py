import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import password_needs_rehash, verify_password
from app.models import User
from app.models.enums import AccountStatus
from tests.conftest import MEMBER_PASSWORD, member_payload
from tests.test_security import older_parameters_hash, passlib_style_hash

URL = "/api/v1/auth/login"


def _register(client: TestClient, db, status: AccountStatus = AccountStatus.ACTIVE) -> User:
    user_id = client.post("/api/v1/auth/register", json=member_payload()).json()["user_id"]
    user = db.get(User, user_id)
    user.account_status = status
    db.commit()
    return user


def test_login_with_mobile_returns_token_and_user(client: TestClient, db) -> None:
    user = _register(client, db)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {"user_id": user.user_id, "first_name": "Ma. Cristina", "role": "member"}
    settings = get_settings()
    claims = jwt.decode(body["access_token"], settings.secret_key, algorithms=["HS256"])
    assert claims["sub"] == str(user.user_id)
    assert claims["role"] == "member"


def test_login_with_email_is_case_insensitive(client: TestClient, db) -> None:
    _register(client, db)

    response = client.post(URL, json={"email": "CRISTINA@Example.com", "password": MEMBER_PASSWORD})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"mobile_no": "+639171234567", "password": "wrong-password"},
        {"mobile_no": "+639180000000", "password": MEMBER_PASSWORD},
        {"email": "nobody@example.com", "password": MEMBER_PASSWORD},
    ],
)
def test_login_bad_credentials_return_401(client: TestClient, db, body: dict) -> None:
    _register(client, db)

    response = client.post(URL, json=body)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (AccountStatus.PENDING, "account_pending"),
        (AccountStatus.DEACTIVATED, "account_deactivated"),
    ],
)
def test_login_inactive_accounts_return_403(
    client: TestClient, db, status: AccountStatus, code: str
) -> None:
    _register(client, db, status=status)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": code}}


def test_login_pending_with_wrong_password_does_not_reveal_status(client: TestClient, db) -> None:
    _register(client, db, status=AccountStatus.PENDING)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}


def _set_hash(db, user: User, password_hash: str) -> None:
    user.password_hash = password_hash
    db.commit()


def _stored_hash(db, user: User) -> str:
    db.expire_all()
    return db.get(User, user.user_id).password_hash


def test_login_accepts_a_passlib_style_hash_and_keeps_it(client: TestClient, db) -> None:
    user = _register(client, db)
    old_hash = passlib_style_hash(MEMBER_PASSWORD)
    _set_hash(db, user, old_hash)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD})

    assert response.status_code == 200
    assert _stored_hash(db, user) == old_hash


def test_login_rehashes_a_hash_with_older_parameters(client: TestClient, db) -> None:
    user = _register(client, db)
    old_hash = older_parameters_hash(MEMBER_PASSWORD)
    _set_hash(db, user, old_hash)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD})

    assert response.status_code == 200
    new_hash = _stored_hash(db, user)
    assert new_hash != old_hash
    assert not password_needs_rehash(new_hash)
    assert verify_password(MEMBER_PASSWORD, new_hash)
    # The password still works on the next login.
    again = client.post(URL, json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD})
    assert again.status_code == 200


@pytest.mark.parametrize(
    ("status", "password", "expected_status"),
    [
        (AccountStatus.ACTIVE, "wrong-password", 401),
        (AccountStatus.PENDING, MEMBER_PASSWORD, 403),
        (AccountStatus.DEACTIVATED, MEMBER_PASSWORD, 403),
    ],
)
def test_login_never_rehashes_when_login_fails(
    client: TestClient, db, status: AccountStatus, password: str, expected_status: int
) -> None:
    user = _register(client, db, status=status)
    old_hash = older_parameters_hash(MEMBER_PASSWORD)
    _set_hash(db, user, old_hash)

    response = client.post(URL, json={"mobile_no": "+639171234567", "password": password})

    assert response.status_code == expected_status
    assert _stored_hash(db, user) == old_hash


@pytest.mark.parametrize(
    "body",
    [
        {"password": MEMBER_PASSWORD},
        {"mobile_no": "+639171234567", "email": "a@example.com", "password": MEMBER_PASSWORD},
        {"mobile_no": "+639171234567"},
        {"mobile_no": "+639171234567", "password": ""},
        {"mobile_no": "+639171234567", "password": MEMBER_PASSWORD, "remember": True},
    ],
)
def test_login_malformed_body_is_422(client: TestClient, body: dict) -> None:
    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
