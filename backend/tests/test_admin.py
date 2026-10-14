import threading
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import SessionLocal, engine
from app.models import User
from app.models.enums import AccountStatus
from app.services import admin_service, auth_service
from tests.conftest import (
    ADMIN_PASSWORD,
    MEMBER_PASSWORD,
    auth_header,
    login_token,
    member_payload,
)

SECOND_ADMIN_MOBILE = "+639990000002"


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


def test_deactivated_admin_gets_account_deactivated_not_not_admin(
    client: TestClient, db, admin_token: str
) -> None:
    admin = _admin(db)
    admin.account_status = AccountStatus.DEACTIVATED
    db.commit()
    user_id = _register(client)

    response = client.patch(
        _status_url(user_id), json={"account_status": "active"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
    assert db.get(User, user_id).account_status == AccountStatus.PENDING


def _admin(db, mobile_no: str = "+639990000001") -> User:
    return db.scalar(select(User).where(User.mobile_no == mobile_no))


def _second_admin(client: TestClient, db) -> tuple[int, str]:
    """Another active coop_admin and its token."""
    admin = auth_service.create_admin(
        db,
        first_name="Jose",
        last_name="Reyes",
        mobile_no=SECOND_ADMIN_MOBILE,
        password=ADMIN_PASSWORD,
        municipality="Mamburao",
    )
    return admin.user_id, login_token(client, SECOND_ADMIN_MOBILE, ADMIN_PASSWORD)


def _status_of(db, user_id: int) -> AccountStatus:
    db.expire_all()
    return db.get(User, user_id).account_status


def test_admin_cannot_deactivate_self(client: TestClient, db, admin_token: str) -> None:
    admin_id = _admin(db).user_id

    response = client.patch(
        _status_url(admin_id),
        json={"account_status": "deactivated"},
        headers=auth_header(admin_token),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cannot_deactivate_self"}}
    assert _status_of(db, admin_id) == AccountStatus.ACTIVE


def test_cannot_deactivate_self_even_with_another_admin(
    client: TestClient, db, admin_token: str
) -> None:
    _second_admin(client, db)
    admin_id = _admin(db).user_id

    response = client.patch(
        _status_url(admin_id),
        json={"account_status": "deactivated"},
        headers=auth_header(admin_token),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cannot_deactivate_self"}}


def test_admin_can_deactivate_another_admin_when_one_remains(
    client: TestClient, db, admin_token: str
) -> None:
    second_id, second_token = _second_admin(client, db)

    response = client.patch(
        _status_url(second_id),
        json={"account_status": "deactivated"},
        headers=auth_header(admin_token),
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": second_id, "account_status": "deactivated"}
    # The deactivated admin's token stops working at once.
    again = client.patch(
        _status_url(_admin(db).user_id),
        json={"account_status": "deactivated"},
        headers=auth_header(second_token),
    )
    assert again.json() == {"detail": {"code": "account_deactivated"}}


def test_last_active_admin_cannot_be_deactivated(db, admin_token: str) -> None:
    """Reachable only when the caller lost admin rights mid-request, so it is driven
    through the service with a caller that is no longer active."""
    only_active = _admin(db)
    caller = auth_service.create_admin(
        db,
        first_name="Jose",
        last_name="Reyes",
        mobile_no=SECOND_ADMIN_MOBILE,
        password=ADMIN_PASSWORD,
        municipality="Mamburao",
    )
    caller.account_status = AccountStatus.DEACTIVATED
    db.commit()

    with pytest.raises(AppError) as error:
        admin_service.set_account_status(db, caller, only_active.user_id, "deactivated")

    assert (error.value.status_code, error.value.code) == (409, "last_active_admin")
    assert _status_of(db, only_active.user_id) == AccountStatus.ACTIVE


def test_admins_deactivating_each_other_at_once_leave_one_active(
    client: TestClient, db, admin_token: str
) -> None:
    """Admin A deactivates admin B while B is deactivating A. A's change holds the lock on
    the active admins until it commits; B's request then waits, sees that A is the last
    active admin, and gets 409 last_active_admin."""
    a_id = _admin(db).user_id
    b_id, b_token = _second_admin(client, db)

    a_session = SessionLocal()
    try:
        b_in_a = a_session.get(User, b_id)
        assert not admin_service._is_last_active_admin(a_session, b_in_a)  # takes the lock
        b_in_a.account_status = AccountStatus.DEACTIVATED
        a_session.flush()

        result: dict = {}
        b_request = threading.Thread(
            target=lambda: result.update(
                response=client.patch(
                    _status_url(a_id),
                    json={"account_status": "deactivated"},
                    headers=auth_header(b_token),
                )
            )
        )
        b_request.start()
        _wait_until_a_request_waits_on_a_lock()
        a_session.commit()
    finally:
        a_session.close()
    b_request.join(timeout=10)

    assert not b_request.is_alive()
    assert result["response"].status_code == 409
    assert result["response"].json() == {"detail": {"code": "last_active_admin"}}
    assert _status_of(db, a_id) == AccountStatus.ACTIVE
    assert _status_of(db, b_id) == AccountStatus.DEACTIVATED


def _wait_until_a_request_waits_on_a_lock(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.scalar(query):
                return
        time.sleep(0.05)
    raise AssertionError("the second request never waited on the admin lock")


@pytest.mark.parametrize(
    ("start", "new_status"),
    [
        (AccountStatus.DEACTIVATED, "active"),
        (AccountStatus.PENDING, "deactivated"),
        (AccountStatus.ACTIVE, "active"),
        (AccountStatus.DEACTIVATED, "deactivated"),
    ],
)
def test_other_status_changes_are_allowed(
    client: TestClient, db, admin_token: str, start: AccountStatus, new_status: str
) -> None:
    """Reactivation, rejecting a sign-up, and setting the current status again (Section 6)."""
    user_id = _register(client)
    db.get(User, user_id).account_status = start
    db.commit()

    response = client.patch(
        _status_url(user_id), json={"account_status": new_status}, headers=auth_header(admin_token)
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": user_id, "account_status": new_status}
    assert _status_of(db, user_id) == AccountStatus(new_status)


def test_admin_can_set_own_status_to_active(client: TestClient, db, admin_token: str) -> None:
    admin_id = _admin(db).user_id

    response = client.patch(
        _status_url(admin_id), json={"account_status": "active"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": admin_id, "account_status": "active"}


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
