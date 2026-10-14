from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models import User
from app.models.enums import AccountStatus
from tests.conftest import MEMBER_PASSWORD, auth_header, member_payload


def _status_url(user_id: int) -> str:
    return f"/api/v1/admin/users/{user_id}/status"


def _register(client: TestClient) -> int:
    return client.post("/api/v1/auth/register", json=member_payload()).json()["user_id"]


def _member_login(client: TestClient):
    return client.post(
        "/api/v1/auth/login", json={"mobile_no": "+639171234567", "password": MEMBER_PASSWORD}
    )


def test_register_pending_approve_login_flow(client: TestClient, admin_token: str) -> None:
    user_id = _register(client)
    assert _member_login(client).json() == {"detail": {"code": "account_pending"}}

    approve = client.patch(
        _status_url(user_id), json={"account_status": "active"}, headers=auth_header(admin_token)
    )
    assert approve.status_code == 200
    assert approve.json() == {"user_id": user_id, "account_status": "active"}

    login = _member_login(client)
    assert login.status_code == 200
    assert login.json()["user"]["first_name"] == "Ma. Cristina"


def test_deactivate_blocks_login(client: TestClient, admin_token: str) -> None:
    user_id = _register(client)
    headers = auth_header(admin_token)
    client.patch(_status_url(user_id), json={"account_status": "active"}, headers=headers)

    response = client.patch(
        _status_url(user_id), json={"account_status": "deactivated"}, headers=headers
    )

    assert response.json() == {"user_id": user_id, "account_status": "deactivated"}
    assert _member_login(client).json() == {"detail": {"code": "account_deactivated"}}


def test_unknown_user_returns_404(client: TestClient, admin_token: str) -> None:
    response = client.patch(
        _status_url(999), json={"account_status": "active"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "user_not_found"}}


def test_member_cannot_change_status(client: TestClient, db, admin_token: str) -> None:
    member_id = _register(client)
    client.patch(
        _status_url(member_id), json={"account_status": "active"}, headers=auth_header(admin_token)
    )
    member_token = _member_login(client).json()["access_token"]

    response = client.patch(
        _status_url(member_id),
        json={"account_status": "deactivated"},
        headers=auth_header(member_token),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_admin"}}
    assert db.get(User, member_id).account_status == AccountStatus.ACTIVE


def test_deactivated_admin_is_not_admin(client: TestClient, db, admin_token: str) -> None:
    admin = db.query(User).filter(User.mobile_no == "+639990000001").one()
    admin.account_status = AccountStatus.DEACTIVATED
    db.commit()
    user_id = _register(client)

    response = client.patch(
        _status_url(user_id), json={"account_status": "active"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_admin"}}


def _expired_token() -> str:
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    return jwt.encode(
        {"sub": "1", "role": "coop_admin", "iat": past, "exp": past + timedelta(minutes=1)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _foreign_token() -> str:
    return jwt.encode(
        {"sub": "1", "role": "coop_admin"}, "a-different-secret-" + "x" * 32, algorithm="HS256"
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic YWRtaW46YWRtaW4="},
        "expired",
        "foreign",
    ],
)
def test_missing_or_invalid_token_returns_401(
    client: TestClient, admin_token: str, headers
) -> None:
    if headers == "expired":
        headers = auth_header(_expired_token())
    elif headers == "foreign":
        headers = auth_header(_foreign_token())

    response = client.patch(_status_url(1), json={"account_status": "active"}, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}
    assert response.headers["www-authenticate"] == "Bearer"


def test_token_for_deleted_user_returns_401(client: TestClient, db, admin_token: str) -> None:
    db.query(User).delete()
    db.commit()

    response = client.patch(
        _status_url(1), json={"account_status": "active"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


@pytest.mark.parametrize(
    "body",
    [{"account_status": "pending"}, {"account_status": "banned"}, {}, {"account_status": None}],
)
def test_invalid_status_body_is_422(client: TestClient, admin_token: str, body: dict) -> None:
    user_id = _register(client)

    response = client.patch(_status_url(user_id), json=body, headers=auth_header(admin_token))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
