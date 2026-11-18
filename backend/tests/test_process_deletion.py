"""POST /admin/users/{user_id}/process-deletion (Phase 13), run only on the test database.
Accounts, passwords and farms here are made-up test data."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import CropCycle, Expense, FarmAssignment, FarmField, HarvestRecord, User
from app.models.enums import AccountStatus, UserRole
from app.services import admin_service, auth_service
from tests.conftest import (
    ADMIN_PASSWORD,
    MEMBER_PASSWORD,
    FarmSetup,
    auth_header,
    login_token,
    member_payload,
)

MEMBER_MOBILE = "+639171234567"
SECOND_ADMIN_MOBILE = "+639990000002"


def _url(user_id: int) -> str:
    return f"/api/v1/admin/users/{user_id}/process-deletion"


def _member(db) -> User:
    return db.scalar(select(User).where(User.role == UserRole.MEMBER))


def _admin(db) -> User:
    return db.scalar(select(User).where(User.mobile_no == "+639990000001"))


def _request_deletion(client: TestClient, token: str) -> None:
    response = client.post("/api/v1/users/me/deletion-request", headers=auth_header(token))
    assert response.status_code == 200


def test_processing_removes_personal_details_and_ends_sessions(
    client: TestClient, db, admin_token: str, member_token: str, farm: FarmSetup
) -> None:
    member = _member(db)
    user_id = member.user_id
    member.barangay_id = db.scalar(text("SELECT barangay_id FROM barangay LIMIT 1"))
    db.commit()
    expense = {
        "category_id": 1,
        "amount_php": 500,
        "expense_date": "2026-07-01",
        "cycle_id": farm.cycle_ids["Field A"],
        "client_uuid": str(uuid.uuid4()),
    }
    created = client.post(
        f"/api/v1/farms/{farm.farm_id}/expenses", json=expense, headers=auth_header(member_token)
    )
    assert created.status_code == 201, created.json()
    _request_deletion(client, member_token)
    db.expire_all()
    requested_at = _member(db).deletion_requested_at
    assert requested_at is not None

    response = client.post(_url(user_id), headers=auth_header(admin_token))

    assert response.status_code == 200
    assert response.json() == {"user_id": user_id, "account_status": "deactivated"}
    db.expire_all()
    user = db.get(User, user_id)
    assert (user.first_name, user.last_name) == ("Deleted", "Member")
    assert user.email is None
    assert user.barangay_id is None
    assert user.mobile_no == f"D{user_id}"
    assert user.member_no == f"deleted-{user_id}"
    assert user.municipality == "Sablayan"  # kept for the cooperative report
    assert user.account_status == AccountStatus.DEACTIVATED
    assert user.deletion_requested_at == requested_at
    assert user.password_changed_at is not None
    assert not user.password_hash.startswith("$argon2")

    # The member's old token is refused at once, as after a password change.
    me = client.get("/api/v1/users/me", headers=auth_header(member_token))
    assert me.json() == {"detail": {"code": "not_authenticated"}}
    # Neither the old mobile number, the old email, nor the new D<user_id> logs in.
    for body in (
        {"mobile_no": MEMBER_MOBILE, "password": MEMBER_PASSWORD},
        {"email": "cristina@example.com", "password": MEMBER_PASSWORD},
        {"mobile_no": f"D{user_id}", "password": MEMBER_PASSWORD},
    ):
        login = client.post("/api/v1/auth/login", json=body)
        assert login.json() == {"detail": {"code": "invalid_credentials"}}

    # The farm records stay for cooperative reports.
    assert db.scalar(
        select(func.count()).select_from(FarmAssignment).where(FarmAssignment.user_id == user_id)
    )
    assert (
        db.scalar(
            select(func.count()).select_from(FarmField).where(FarmField.farm_id == farm.farm_id)
        )
        == 2
    )
    assert db.get(CropCycle, farm.cycle_ids["Field A"]) is not None
    assert db.scalar(select(func.count()).select_from(Expense)) == 1
    assert db.scalar(select(func.count()).select_from(HarvestRecord)) == 0


def test_old_login_ids_are_free_for_a_new_sign_up(
    client: TestClient, db, admin_token: str, member_token: str
) -> None:
    user_id = _member(db).user_id
    _request_deletion(client, member_token)
    client.post(_url(user_id), headers=auth_header(admin_token))

    response = client.post("/api/v1/auth/register", json=member_payload())

    assert response.status_code == 201, response.json()


def test_a_reactivated_processed_account_still_cannot_log_in(
    client: TestClient, db, admin_token: str, member_token: str
) -> None:
    user_id = _member(db).user_id
    _request_deletion(client, member_token)
    headers = auth_header(admin_token)
    client.post(_url(user_id), headers=headers)

    reactivate = client.patch(
        f"/api/v1/admin/users/{user_id}/status", json={"account_status": "active"}, headers=headers
    )

    assert reactivate.status_code == 200
    login = client.post(
        "/api/v1/auth/login", json={"mobile_no": f"D{user_id}", "password": MEMBER_PASSWORD}
    )
    assert login.json() == {"detail": {"code": "invalid_credentials"}}


def test_processing_again_changes_nothing(
    client: TestClient, db, admin_token: str, member_token: str
) -> None:
    user_id = _member(db).user_id
    _request_deletion(client, member_token)
    headers = auth_header(admin_token)
    client.post(_url(user_id), headers=headers)
    db.expire_all()
    first = db.get(User, user_id)
    before = (first.password_changed_at, first.mobile_no, first.member_no, first.first_name)

    again = client.post(_url(user_id), headers=headers)

    assert again.status_code == 200
    assert again.json() == {"user_id": user_id, "account_status": "deactivated"}
    db.expire_all()
    user = db.get(User, user_id)
    assert (user.password_changed_at, user.mobile_no, user.member_no, user.first_name) == before


def test_unknown_user(client: TestClient, admin_token: str) -> None:
    response = client.post(_url(999999), headers=auth_header(admin_token))
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "user_not_found"}}


def test_no_deletion_request(client: TestClient, db, admin_token: str, member_token: str) -> None:
    user_id = _member(db).user_id

    response = client.post(_url(user_id), headers=auth_header(admin_token))

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "no_deletion_request"}}
    db.expire_all()
    assert db.get(User, user_id).mobile_no == MEMBER_MOBILE


def test_no_deletion_request_is_checked_before_self(
    client: TestClient, db, admin_token: str
) -> None:
    response = client.post(_url(_admin(db).user_id), headers=auth_header(admin_token))
    assert response.json() == {"detail": {"code": "no_deletion_request"}}


def test_cannot_process_own_request(client: TestClient, db, admin_token: str) -> None:
    _request_deletion(client, admin_token)

    response = client.post(_url(_admin(db).user_id), headers=auth_header(admin_token))

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cannot_deactivate_self"}}
    db.expire_all()
    assert _admin(db).account_status == AccountStatus.ACTIVE


def test_another_admin_request_is_processed_while_one_admin_remains(
    client: TestClient, db, admin_token: str
) -> None:
    second = auth_service.create_admin(
        db,
        first_name="Jose",
        last_name="Reyes",
        mobile_no=SECOND_ADMIN_MOBILE,
        password=ADMIN_PASSWORD,
        municipality="Mamburao",
    )
    second_id = second.user_id
    _request_deletion(client, login_token(client, SECOND_ADMIN_MOBILE, ADMIN_PASSWORD))

    response = client.post(_url(second_id), headers=auth_header(admin_token))

    assert response.status_code == 200
    db.expire_all()
    assert db.get(User, second_id).member_no == f"deleted-{second_id}"


def test_last_active_admin(db, admin_token: str) -> None:
    """Reachable only when the caller lost admin rights mid-request, so it is driven
    through the service with a caller that is no longer active (as in test_admin.py)."""
    only_active = _admin(db)
    only_active.deletion_requested_at = func.now()
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
        admin_service.process_deletion(db, caller, only_active.user_id)

    assert (error.value.status_code, error.value.code) == (409, "last_active_admin")
    db.expire_all()
    assert _admin(db).account_status == AccountStatus.ACTIVE


def test_mobile_check_accepts_only_the_deleted_form(db, member_token: str) -> None:
    member = _member(db)
    member.mobile_no = "X123"
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    member = _member(db)
    member.mobile_no = f"D{member.user_id}"
    db.commit()


def test_0011_upgrade_downgrade_upgrade(db, member_token: str) -> None:
    from alembic import command

    from tests.conftest import alembic_config

    user_id = _member(db).user_id
    db.close()
    config = alembic_config()
    command.downgrade(config, "0010")
    try:
        with pytest.raises(IntegrityError):
            with db.bind.begin() as connection:
                connection.execute(
                    text("UPDATE users SET mobile_no = :m WHERE user_id = :id"),
                    {"m": f"D{user_id}", "id": user_id},
                )
    finally:
        command.upgrade(config, "head")
    with db.bind.begin() as connection:
        connection.execute(
            text("UPDATE users SET mobile_no = :m WHERE user_id = :id"),
            {"m": f"D{user_id}", "id": user_id},
        )
