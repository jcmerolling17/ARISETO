"""GET /notifications, PATCH /notifications/{id}/read, and POST /notifications/read-all: a
member only ever sees and changes their own notifications."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Notification, User
from app.models.enums import NotificationType
from tests.conftest import auth_header

URL = "/api/v1/notifications"
BASE = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


def _user_id(db, mobile_no: str) -> int:
    return db.scalar(select(User.user_id).where(User.mobile_no == mobile_no))


def _add(db, user_id: int, minutes: int, **values) -> int:
    """A notification created `minutes` after BASE. Task reminders need no weather alert,
    so they stand in for the rows the alert engine makes."""
    fields = {
        "type": NotificationType.TASK_REMINDER,
        "title": f"Notice {minutes}",
        "body": "Body text",
        "severity": "info",
        "created_at": BASE + timedelta(minutes=minutes),
    }
    row = Notification(user_id=user_id, **(fields | values))
    db.add(row)
    db.commit()
    return row.notification_id


@pytest.fixture
def owner_id(db, member_token: str) -> int:
    return _user_id(db, "+639171234567")


@pytest.fixture
def outsider_id(db, outsider_token: str) -> int:
    return _user_id(db, "+639172222222")


def test_lists_own_notifications_newest_first(
    client: TestClient, db, member_token: str, owner_id: int, outsider_id: int
) -> None:
    first = _add(db, owner_id, 1)
    second = _add(db, owner_id, 2, read_at=BASE + timedelta(hours=1))
    _add(db, outsider_id, 3)

    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 1
    assert [item["notification_id"] for item in body["items"]] == [second, first]
    assert body["items"][1] == {
        "notification_id": first,
        "type": "task_reminder",
        "title": "Notice 1",
        "body": "Body text",
        "severity": "info",
        "farm_id": None,
        "created_at": "2026-11-03T06:01:00Z",
        "read_at": None,
    }


def test_a_tie_on_created_at_shows_the_higher_id_first(
    client: TestClient, db, member_token: str, owner_id: int
) -> None:
    ids = [_add(db, owner_id, 5) for _ in range(3)]
    items = client.get(URL, headers=auth_header(member_token)).json()["items"]
    assert [item["notification_id"] for item in items] == ids[::-1]


def test_empty_list(client: TestClient, member_token: str) -> None:
    response = client.get(URL, headers=auth_header(member_token))
    assert response.json() == {"unread_count": 0, "items": []}


def test_unread_only_and_unread_count_ignores_filters(
    client: TestClient, db, member_token: str, owner_id: int
) -> None:
    unread = _add(db, owner_id, 1)
    _add(db, owner_id, 2, read_at=BASE)
    _add(db, owner_id, 3, type=NotificationType.GROWTH_STAGE)

    body = client.get(
        URL,
        params={"unread_only": "true", "type": "task_reminder"},
        headers=auth_header(member_token),
    ).json()

    assert [item["notification_id"] for item in body["items"]] == [unread]
    assert body["unread_count"] == 2


def test_type_filter(client: TestClient, db, member_token: str, owner_id: int) -> None:
    growth = _add(db, owner_id, 1, type=NotificationType.GROWTH_STAGE)
    _add(db, owner_id, 2)

    items = client.get(
        URL, params={"type": "growth_stage"}, headers=auth_header(member_token)
    ).json()["items"]
    assert [item["notification_id"] for item in items] == [growth]


def test_limit_and_offset(client: TestClient, db, member_token: str, owner_id: int) -> None:
    ids = [_add(db, owner_id, minutes) for minutes in range(5)]
    items = client.get(
        URL, params={"limit": 2, "offset": 1}, headers=auth_header(member_token)
    ).json()["items"]
    assert [item["notification_id"] for item in items] == [ids[3], ids[2]]


def test_default_limit_is_20(client: TestClient, db, member_token: str, owner_id: int) -> None:
    for minutes in range(21):
        _add(db, owner_id, minutes)
    body = client.get(URL, headers=auth_header(member_token)).json()
    assert len(body["items"]) == 20
    assert body["unread_count"] == 21


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"type": "expense_saved"}, {"unread_only": "x"}],
)
def test_bad_query_is_fastapi_422(client: TestClient, member_token: str, params: dict) -> None:
    response = client.get(URL, params=params, headers=auth_header(member_token))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# ---------- Mark one read ----------


def _read(client: TestClient, token: str, notification_id: int):
    return client.patch(f"{URL}/{notification_id}/read", headers=auth_header(token))


def test_marks_a_notification_read_once(
    client: TestClient, db, member_token: str, owner_id: int
) -> None:
    notification_id = _add(db, owner_id, 1)

    first = _read(client, member_token, notification_id)
    assert first.status_code == 200
    assert first.json()["notification_id"] == notification_id
    read_at = first.json()["read_at"]
    assert read_at is not None

    again = _read(client, member_token, notification_id)
    assert again.status_code == 200
    assert again.json()["read_at"] == read_at
    assert client.get(URL, headers=auth_header(member_token)).json()["unread_count"] == 0


def test_someone_elses_notification_is_not_found(
    client: TestClient, db, member_token: str, outsider_id: int
) -> None:
    notification_id = _add(db, outsider_id, 1)

    response = _read(client, member_token, notification_id)

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "notification_not_found"}}
    db.expire_all()
    assert db.get(Notification, notification_id).read_at is None


def test_unknown_notification_is_not_found(client: TestClient, member_token: str) -> None:
    response = _read(client, member_token, 999)
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "notification_not_found"}}


# ---------- Mark all read ----------


def test_read_all_marks_only_the_callers_unread(
    client: TestClient, db, member_token: str, owner_id: int, outsider_id: int
) -> None:
    _add(db, owner_id, 1)
    _add(db, owner_id, 2)
    already = _add(db, owner_id, 3, read_at=BASE)
    others = _add(db, outsider_id, 4)

    response = client.post(f"{URL}/read-all", headers=auth_header(member_token))

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    db.expire_all()
    assert db.get(Notification, already).read_at == BASE
    assert db.get(Notification, others).read_at is None
    assert client.get(URL, headers=auth_header(member_token)).json()["unread_count"] == 0
    assert client.post(f"{URL}/read-all", headers=auth_header(member_token)).json() == {
        "updated": 0
    }


def test_admins_have_their_own_list(client: TestClient, admin_token: str) -> None:
    response = client.get(URL, headers=auth_header(admin_token))
    assert response.status_code == 200
    assert response.json() == {"unread_count": 0, "items": []}
