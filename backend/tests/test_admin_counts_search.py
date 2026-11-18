"""GET /admin/users/counts and the role, q and deletion_requested filters of GET /admin/users
(Phase 13). Every account here is made-up test data."""

from fastapi.testclient import TestClient

from app.models.enums import AccountStatus
from tests.conftest import (
    MEMBER_PASSWORD,
    auth_header,
    create_active_member,
    login_token,
    member_payload,
)

USERS = "/api/v1/admin/users"


def _member(db, n: int, status: AccountStatus, **overrides):
    user = create_active_member(
        db,
        mobile_no=f"+63917000000{n}",
        email=f"member{n}@example.com",
        member_no=f"MPMPC-100{n}",
        **overrides,
    )
    user.account_status = status
    db.commit()
    return user


def _ids(response) -> list[int]:
    assert response.status_code == 200, response.json()
    return [row["user_id"] for row in response.json()]


def test_counts_cover_members_only_and_unprocessed_deletion_requests(
    client: TestClient, db, admin_token: str
) -> None:
    headers = auth_header(admin_token)
    _member(db, 1, AccountStatus.PENDING)
    _member(db, 2, AccountStatus.PENDING)
    asked = _member(db, 3, AccountStatus.ACTIVE)
    processed = _member(db, 4, AccountStatus.ACTIVE)
    _member(db, 5, AccountStatus.DEACTIVATED)
    for user in (asked, processed):
        token = login_token(client, user.mobile_no, MEMBER_PASSWORD)
        client.post("/api/v1/users/me/deletion-request", headers=auth_header(token))
    assert (
        client.post(f"{USERS}/{processed.user_id}/process-deletion", headers=headers).status_code
        == 200
    )

    response = client.get(f"{USERS}/counts", headers=headers)

    assert response.status_code == 200
    # The admin account is not a member; the processed request moves to deactivated.
    assert response.json() == {
        "pending": 2,
        "active": 1,
        "deactivated": 2,
        "deletion_requested": 1,
    }
    assert _ids(client.get(USERS, params={"deletion_requested": "true"}, headers=headers)) == [
        asked.user_id
    ]


def test_role_filter(client: TestClient, db, admin_token: str) -> None:
    headers = auth_header(admin_token)
    member = _member(db, 1, AccountStatus.PENDING)

    members = client.get(USERS, params={"role": "member"}, headers=headers).json()
    admins = client.get(USERS, params={"role": "coop_admin"}, headers=headers).json()

    assert [row["user_id"] for row in members] == [member.user_id]
    assert [row["role"] for row in admins] == ["coop_admin"]
    assert client.get(USERS, params={"role": "owner"}, headers=headers).status_code == 422


def test_q_searches_names_mobile_and_member_number_ignoring_case(
    client: TestClient, db, admin_token: str
) -> None:
    headers = auth_header(admin_token)
    juan = _member(db, 1, AccountStatus.PENDING, first_name="Juan", last_name="Bautista")
    rosa = _member(db, 2, AccountStatus.ACTIVE, first_name="Rosa", last_name="Mercado")

    def search(q: str, **params) -> list[int]:
        return _ids(client.get(USERS, params={"q": q, "role": "member", **params}, headers=headers))

    assert search("JUAN") == [juan.user_id]
    assert search("bautista") == [juan.user_id]
    assert search("juan baut") == [juan.user_id]  # first and last name together
    assert search("mpmpc-1002") == [rosa.user_id]
    assert search("+639170000001") == [juan.user_id]
    assert search("09170000002") == [rosa.user_id]  # 09 is also tried as +639
    assert search("9170000002") == [rosa.user_id]
    assert sorted(search("mpmpc")) == sorted([juan.user_id, rosa.user_id])
    assert search("mercado bautista") == []
    assert search("%") == []  # % and _ are matched literally
    assert search("_") == []
    assert search("juan", status="active") == []
    assert search("  ") == sorted([rosa.user_id, juan.user_id], reverse=True)


def test_q_too_long_is_rejected(client: TestClient, admin_token: str) -> None:
    response = client.get(USERS, params={"q": "x" * 101}, headers=auth_header(admin_token))
    assert response.status_code == 422


def test_new_admin_endpoints_are_for_administrators_only(
    client: TestClient, db, member_token: str
) -> None:
    member = auth_header(member_token)
    for method, path in (
        ("get", f"{USERS}/counts"),
        ("post", f"{USERS}/1/process-deletion"),
        ("get", "/api/v1/admin/reports/cooperative"),
    ):
        assert getattr(client, method)(path, headers=member).json() == {
            "detail": {"code": "not_admin"}
        }
        assert getattr(client, method)(path).status_code == 401


def test_pending_member_payload_still_has_the_documented_fields(
    client: TestClient, admin_token: str
) -> None:
    client.post("/api/v1/auth/register", json=member_payload())
    rows = client.get(USERS, params={"q": "cristina"}, headers=auth_header(admin_token)).json()
    assert set(rows[0]) == {
        "user_id",
        "first_name",
        "last_name",
        "mobile_no",
        "email",
        "member_no",
        "municipality",
        "barangay_name",
        "role",
        "account_status",
        "created_at",
        "deletion_requested_at",
    }
