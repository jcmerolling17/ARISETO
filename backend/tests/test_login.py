import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models import User
from app.models.enums import AccountStatus
from tests.conftest import MEMBER_PASSWORD, member_payload

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

    response = client.post(
        URL, json={"email": "CRISTINA@Example.com", "password": MEMBER_PASSWORD}
    )

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
