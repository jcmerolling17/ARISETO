"""GET and PATCH /users/me, POST /users/me/password, POST /users/me/deletion-request."""

import pytest
from fastapi.testclient import TestClient

from app.models import User
from tests.conftest import (
    ADMIN_PASSWORD,
    MEMBER_PASSWORD,
    TANGKALAN,
    auth_header,
    create_active_member,
    login_token,
)

ME = "/api/v1/users/me"
PASSWORD = "/api/v1/users/me/password"
DELETION = "/api/v1/users/me/deletion-request"
LOGIN = "/api/v1/auth/login"
MOBILE = "+639171234567"
OTHER_MOBILE = "+639181111111"


def _other_member(db) -> User:
    return create_active_member(
        db, mobile_no=OTHER_MOBILE, email="other@example.com", member_no="MPMPC-0099"
    )


def _login(client: TestClient, password: str, mobile_no: str = MOBILE):
    return client.post(LOGIN, json={"mobile_no": mobile_no, "password": password})


# ---------- GET /users/me ----------


def test_get_me_returns_the_profile_with_the_barangay_name(
    client: TestClient, db, barangay_id: int
) -> None:
    user = create_active_member(db, municipality="Mamburao", barangay_id=barangay_id)
    token = login_token(client, MOBILE, MEMBER_PASSWORD)

    response = client.get(ME, headers=auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "user_id": user.user_id,
        "first_name": "Ma. Cristina",
        "last_name": "Dela Cruz",
        "mobile_no": MOBILE,
        "email": "cristina@example.com",
        "member_no": "MPMPC-0042",
        "municipality": "Mamburao",
        "barangay_id": barangay_id,
        "barangay_name": TANGKALAN["barangay_name"],
        "preferred_language": "fil",
        "role": "member",
        "account_status": "active",
        "created_at": body["created_at"],
        "deletion_requested_at": None,
    }
    assert "password_hash" not in body


def test_get_me_without_a_barangay(client: TestClient, member_token: str) -> None:
    body = client.get(ME, headers=auth_header(member_token)).json()

    assert body["barangay_id"] is None
    assert body["barangay_name"] is None


def test_get_me_for_a_coop_admin_without_member_number(
    client: TestClient, admin_token: str
) -> None:
    body = client.get(ME, headers=auth_header(admin_token)).json()

    assert body["role"] == "coop_admin"
    assert body["member_no"] is None


# ---------- PATCH /users/me ----------


def test_update_names_and_language_without_a_password(
    client: TestClient, member_token: str
) -> None:
    response = client.patch(
        ME,
        json={"first_name": "  Juan   Carlos ", "last_name": "Reyes", "preferred_language": "en"},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["first_name"], body["last_name"], body["preferred_language"]) == (
        "Juan Carlos",
        "Reyes",
        "en",
    )
    assert client.get(ME, headers=auth_header(member_token)).json() == body


def test_update_with_an_empty_body_changes_nothing(client: TestClient, member_token: str) -> None:
    before = client.get(ME, headers=auth_header(member_token)).json()

    response = client.patch(ME, json={}, headers=auth_header(member_token))

    assert response.status_code == 200
    assert response.json() == before


@pytest.mark.parametrize(
    "change", [{"email": "new@example.com"}, {"email": None}, {"mobile_no": OTHER_MOBILE}]
)
def test_login_id_change_without_password_is_422(
    client: TestClient, db, member_token: str, change: dict
) -> None:
    response = client.patch(ME, json=change, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "current_password_required"}}
    db.expire_all()
    assert db.query(User).one().email == "cristina@example.com"


@pytest.mark.parametrize("change", [{"email": "new@example.com"}, {"mobile_no": OTHER_MOBILE}])
def test_login_id_change_with_wrong_password_is_403(
    client: TestClient, db, member_token: str, change: dict
) -> None:
    response = client.patch(
        ME, json={**change, "current_password": "wrong-password"}, headers=auth_header(member_token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "invalid_current_password"}}
    db.expire_all()
    user = db.query(User).one()
    assert (user.mobile_no, user.email) == (MOBILE, "cristina@example.com")


def test_email_change_is_saved_lowercase(client: TestClient, member_token: str) -> None:
    response = client.patch(
        ME,
        json={"email": "New.Address@Example.COM", "current_password": MEMBER_PASSWORD},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new.address@example.com"
    assert (
        client.post(
            LOGIN, json={"email": "new.address@example.com", "password": MEMBER_PASSWORD}
        ).status_code
        == 200
    )


def test_email_can_be_cleared_with_the_password(client: TestClient, member_token: str) -> None:
    response = client.patch(
        ME,
        json={"email": None, "current_password": MEMBER_PASSWORD},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    assert response.json()["email"] is None
    assert (
        client.post(
            LOGIN, json={"email": "cristina@example.com", "password": MEMBER_PASSWORD}
        ).status_code
        == 401
    )


def test_mobile_change_becomes_the_login_id(client: TestClient, member_token: str) -> None:
    response = client.patch(
        ME,
        json={"mobile_no": OTHER_MOBILE, "current_password": MEMBER_PASSWORD},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    assert response.json()["mobile_no"] == OTHER_MOBILE
    assert _login(client, MEMBER_PASSWORD, OTHER_MOBILE).status_code == 200
    assert _login(client, MEMBER_PASSWORD, MOBILE).status_code == 401
    # Changing a login ID does not end the session.
    assert client.get(ME, headers=auth_header(member_token)).status_code == 200


def test_sending_the_current_login_ids_needs_no_password(
    client: TestClient, member_token: str
) -> None:
    response = client.patch(
        ME,
        json={"mobile_no": MOBILE, "email": "CRISTINA@example.com", "first_name": "Cristina"},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    assert response.json()["first_name"] == "Cristina"


def test_password_is_ignored_when_no_login_id_changes(
    client: TestClient, member_token: str
) -> None:
    response = client.patch(
        ME,
        json={"last_name": "Santos", "current_password": "wrong-password"},
        headers=auth_header(member_token),
    )

    assert response.status_code == 200
    assert response.json()["last_name"] == "Santos"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"mobile_no": OTHER_MOBILE}, "mobile_taken"),
        ({"email": "other@example.com"}, "email_taken"),
    ],
)
def test_login_id_taken_by_another_account_is_409(
    client: TestClient, db, member_token: str, change: dict, code: str
) -> None:
    _other_member(db)

    response = client.patch(
        ME, json={**change, "current_password": MEMBER_PASSWORD}, headers=auth_header(member_token)
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": code}}


def test_password_is_checked_before_a_taken_login_id(
    client: TestClient, db, member_token: str
) -> None:
    """Without the right password, the answer never shows whether a number is taken."""
    _other_member(db)

    response = client.patch(
        ME,
        json={"mobile_no": OTHER_MOBILE, "current_password": "wrong-password"},
        headers=auth_header(member_token),
    )

    assert response.json() == {"detail": {"code": "invalid_current_password"}}


@pytest.mark.parametrize(
    "body",
    [
        {"first_name": None},
        {"last_name": None},
        {"mobile_no": None},
        {"preferred_language": None},
        {"first_name": ""},
        {"first_name": "x" * 61},
        {"mobile_no": "09171234567"},
        {"email": "not-an-email"},
        {"preferred_language": "es"},
        {"member_no": "MPMPC-0001"},
        {"municipality": "Mamburao"},
        {"role": "coop_admin"},
        {"account_status": "active"},
    ],
)
def test_update_invalid_body_uses_fastapi_422(
    client: TestClient, member_token: str, body: dict
) -> None:
    response = client.patch(
        ME, json={**body, "current_password": MEMBER_PASSWORD}, headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# ---------- POST /users/me/password ----------


def _change(client: TestClient, token: str, current: str, new: str):
    return client.post(
        PASSWORD,
        json={"current_password": current, "new_password": new},
        headers=auth_header(token),
    )


def test_password_change_returns_a_working_token_and_ends_other_sessions(
    client: TestClient, db, member_token: str
) -> None:
    response = _change(client, member_token, MEMBER_PASSWORD, "brand-new-pass")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert set(body) == {"access_token", "token_type"}
    assert client.get(ME, headers=auth_header(body["access_token"])).status_code == 200
    old = client.get(ME, headers=auth_header(member_token))
    assert old.status_code == 401
    assert old.json() == {"detail": {"code": "not_authenticated"}}
    assert db.query(User).one().password_changed_at is not None


def test_password_change_moves_the_login_to_the_new_password(
    client: TestClient, member_token: str
) -> None:
    _change(client, member_token, MEMBER_PASSWORD, "brand-new-pass")

    assert _login(client, MEMBER_PASSWORD).status_code == 401
    login = _login(client, "brand-new-pass")
    assert login.status_code == 200
    # A login after the change is not older than it.
    assert client.get(ME, headers=auth_header(login.json()["access_token"])).status_code == 200


def test_a_second_change_ends_the_first_changes_token(
    client: TestClient, member_token: str
) -> None:
    first = _change(client, member_token, MEMBER_PASSWORD, "brand-new-pass").json()["access_token"]
    second = _change(client, first, "brand-new-pass", "another-pass-1").json()["access_token"]

    assert client.get(ME, headers=auth_header(first)).status_code == 401
    assert client.get(ME, headers=auth_header(second)).status_code == 200


def test_password_change_with_wrong_current_password_is_403(
    client: TestClient, db, member_token: str
) -> None:
    response = _change(client, member_token, "wrong-password", "brand-new-pass")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "invalid_current_password"}}
    assert db.query(User).one().password_changed_at is None
    assert client.get(ME, headers=auth_header(member_token)).status_code == 200


def test_new_password_same_as_current_is_422(client: TestClient, db, member_token: str) -> None:
    response = _change(client, member_token, MEMBER_PASSWORD, MEMBER_PASSWORD)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "password_unchanged"}}
    assert db.query(User).one().password_changed_at is None


@pytest.mark.parametrize("length", [8, 128])
def test_new_password_of_8_to_128_characters_is_accepted(
    client: TestClient, member_token: str, length: int
) -> None:
    assert _change(client, member_token, MEMBER_PASSWORD, "p" * length).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"current_password": MEMBER_PASSWORD, "new_password": "p" * 7},
        {"current_password": MEMBER_PASSWORD, "new_password": "p" * 129},
        {"current_password": MEMBER_PASSWORD},
        {"new_password": "brand-new-pass"},
        {"current_password": "", "new_password": "brand-new-pass"},
        {"current_password": MEMBER_PASSWORD, "new_password": "brand-new-pass", "x": 1},
    ],
)
def test_password_change_invalid_body_uses_fastapi_422(
    client: TestClient, member_token: str, body: dict
) -> None:
    response = client.post(PASSWORD, json=body, headers=auth_header(member_token))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_coop_admin_can_change_their_password(client: TestClient, admin_token: str) -> None:
    assert _change(client, admin_token, ADMIN_PASSWORD, "admin-new-pass").status_code == 200


# ---------- POST /users/me/deletion-request ----------


def test_deletion_request_records_the_time(client: TestClient, member_token: str) -> None:
    response = client.post(DELETION, headers=auth_header(member_token))

    assert response.status_code == 200
    requested = response.json()["deletion_requested_at"]
    assert requested is not None
    assert (
        client.get(ME, headers=auth_header(member_token)).json()["deletion_requested_at"]
        == requested
    )


def test_asking_again_keeps_the_first_time(client: TestClient, member_token: str) -> None:
    first = client.post(DELETION, headers=auth_header(member_token)).json()

    second = client.post(DELETION, headers=auth_header(member_token))

    assert second.status_code == 200
    assert second.json() == first


def test_deletion_request_leaves_the_account_active(
    client: TestClient, db, member_token: str
) -> None:
    client.post(DELETION, headers=auth_header(member_token))

    db.expire_all()
    assert db.query(User).one().account_status == "active"
    assert client.get(ME, headers=auth_header(member_token)).status_code == 200
