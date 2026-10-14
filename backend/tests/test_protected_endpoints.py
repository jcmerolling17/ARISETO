"""Every protected endpoint goes through the shared account check (Section 6): 401
not_authenticated without a valid token, and the account status is checked before any role
or farm check, so an inactive account's token gets 403 account_deactivated or account_pending."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import User
from app.models.enums import AccountStatus
from tests.conftest import MEMBER_PASSWORD, auth_header, create_active_member, login_token

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/barangays"),
}

PROTECTED = {
    ("GET", "/api/v1/crops"),
    ("GET", "/api/v1/farms"),
    ("POST", "/api/v1/farms"),
    ("POST", "/api/v1/farms/{farm_id}/fields"),
    ("GET", "/api/v1/farms/{farm_id}/weather"),
    ("PATCH", "/api/v1/admin/users/{user_id}/status"),
}


def _api_routes() -> set[tuple[str, str]]:
    """Every API endpoint, read from the OpenAPI schema (FastAPI keeps included routers
    nested, so app.routes does not list them)."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
    }


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_api_route_is_listed_as_public_or_protected() -> None:
    assert _api_routes() == PUBLIC | PROTECTED


def _set_status(db, user_id: int, status: AccountStatus) -> None:
    db.get(User, user_id).account_status = status
    db.commit()


@pytest.fixture
def member_id_and_token(client: TestClient, db) -> tuple[int, str]:
    """An active member and its token; tests change the status after login."""
    user_id = create_active_member(db).user_id
    return user_id, login_token(client, "+639171234567", MEMBER_PASSWORD)


@pytest.fixture
def admin_id(db, admin_token: str) -> int:
    return db.query(User).filter(User.mobile_no == "+639990000001").one().user_id


@pytest.mark.parametrize(("method", "path"), sorted(PROTECTED))
def test_missing_token_is_401(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, _url(path), json={})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


@pytest.mark.parametrize(("method", "path"), sorted(PROTECTED))
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (AccountStatus.DEACTIVATED, "account_deactivated"),
        (AccountStatus.PENDING, "account_pending"),
    ],
)
def test_inactive_member_token_is_refused(
    client: TestClient,
    db,
    member_id_and_token: tuple[int, str],
    method: str,
    path: str,
    status: AccountStatus,
    code: str,
) -> None:
    user_id, token = member_id_and_token
    _set_status(db, user_id, status)

    response = client.request(method, _url(path), json={}, headers=auth_header(token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": code}}


@pytest.mark.parametrize(("method", "path"), sorted(PROTECTED))
def test_deactivated_coop_admin_token_is_refused(
    client: TestClient, db, admin_token: str, admin_id: int, method: str, path: str
) -> None:
    _set_status(db, admin_id, AccountStatus.DEACTIVATED)

    response = client.request(method, _url(path), json={}, headers=auth_header(admin_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
