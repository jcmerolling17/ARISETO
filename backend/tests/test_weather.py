from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FarmAssignment, User, WeatherLog
from app.models.enums import AccountStatus, FarmRole
from tests.conftest import MEMBER_PASSWORD, auth_header, create_active_member, login_token

EMPTY = {"current": None, "forecast": [], "alerts": []}


@pytest.fixture
def farm_id(client: TestClient, member_token: str, barangay_id: int, variety_ids) -> int:
    body = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "season": "wet",
        "fields": [
            {
                "field_name": "Field A",
                "area_ha": 1.25,
                "variety_id": variety_ids["NK6410"],
                "planting_date": date.today().isoformat(),
            }
        ],
    }
    return client.post("/api/v1/farms", json=body, headers=auth_header(member_token)).json()[
        "farm_id"
    ]


def _url(farm_id: int) -> str:
    return f"/api/v1/farms/{farm_id}/weather"


def _reading(farm_id: int, forecast_for: datetime, fetched_at: datetime, **values) -> WeatherLog:
    row = {
        "temp_c": Decimal("29.4"),
        "feels_like_c": Decimal("33.1"),
        "humidity_pct": 74,
        "rain_mm": Decimal("0"),
        "precip_probability_pct": 20,
        "wind_speed_mps": Decimal("3.6"),
        "condition_code": 802,
        "is_forecast": False,
    }
    row.update(values)
    return WeatherLog(farm_id=farm_id, forecast_for=forecast_for, fetched_at=fetched_at, **row)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def test_empty_until_the_first_fetch(client: TestClient, member_token: str, farm_id: int) -> None:
    response = client.get(_url(farm_id), headers=auth_header(member_token))

    assert response.status_code == 200
    assert response.json() == EMPTY


def test_returns_latest_reading_and_upcoming_forecast(
    client: TestClient, db, member_token: str, farm_id: int
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    earlier, latest = now - timedelta(hours=3), now - timedelta(minutes=20)
    in_3h, in_6h = now + timedelta(hours=3), now + timedelta(hours=6)
    db.add_all(
        [
            _reading(farm_id, earlier, earlier, temp_c=Decimal("27")),
            _reading(farm_id, latest, latest),
            # A slot that already passed, and one slot fetched twice.
            _reading(farm_id, now - timedelta(hours=1), earlier, is_forecast=True),
            _reading(farm_id, in_3h, earlier, is_forecast=True, rain_mm=Decimal("1")),
            _reading(
                farm_id, in_3h, latest, is_forecast=True, rain_mm=Decimal("4.2"), condition_code=500
            ),
            _reading(farm_id, in_6h, latest, is_forecast=True, humidity_pct=None),
        ]
    )
    db.commit()

    response = client.get(_url(farm_id), headers=auth_header(member_token))

    assert response.status_code == 200
    body = response.json()
    assert body["current"] == {
        "temp_c": 29.4,
        "feels_like_c": 33.1,
        "humidity_pct": 74,
        "wind_speed_mps": 3.6,
        "precip_probability_pct": 20,
        "rain_mm": 0.0,
        "condition_code": 802,
        "fetched_at": _iso(latest),
    }
    assert [
        (slot["forecast_for"], slot["rain_mm"], slot["condition_code"], slot["humidity_pct"])
        for slot in body["forecast"]
    ] == [(_iso(in_3h), 4.2, 500, 74), (_iso(in_6h), 0.0, 802, None)]
    assert body["alerts"] == []


def test_other_farms_weather_is_not_mixed_in(
    client: TestClient,
    db,
    member_token: str,
    admin_token: str,
    farm_id: int,
    barangay_id: int,
    variety_ids,
) -> None:
    other = client.post(
        "/api/v1/farms",
        json={
            "farm_name": "Admin Farm",
            "barangay_id": barangay_id,
            "season": "wet",
            "fields": [
                {
                    "field_name": "Field A",
                    "area_ha": 1,
                    "variety_id": variety_ids["NK6410"],
                    "planting_date": date.today().isoformat(),
                }
            ],
        },
        headers=auth_header(admin_token),
    ).json()["farm_id"]
    now = datetime.now(UTC)
    db.add(_reading(other, now, now))
    db.commit()

    response = client.get(_url(farm_id), headers=auth_header(member_token))

    assert response.json() == EMPTY


def test_any_member_of_the_farm_can_read_it(
    client: TestClient, db, farm_id: int, member_token: str
) -> None:
    worker = create_active_member(
        db, mobile_no="+639171111111", email="pedro@example.com", member_no="MPMPC-0043"
    )
    db.add(FarmAssignment(farm_id=farm_id, user_id=worker.user_id, role_on_farm=FarmRole.WORKER))
    db.commit()
    token = login_token(client, "+639171111111", MEMBER_PASSWORD)

    response = client.get(_url(farm_id), headers=auth_header(token))

    assert response.status_code == 200


@pytest.mark.parametrize("who", ["other_member", "admin"])
def test_non_members_are_refused(
    client: TestClient, db, farm_id: int, admin_token: str, who: str
) -> None:
    if who == "admin":
        token = admin_token
    else:
        create_active_member(
            db, mobile_no="+639171111111", email="pedro@example.com", member_no="MPMPC-0043"
        )
        token = login_token(client, "+639171111111", MEMBER_PASSWORD)

    response = client.get(_url(farm_id), headers=auth_header(token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_member"}}


def test_unknown_farm_is_not_farm_member(
    client: TestClient, member_token: str, farm_id: int
) -> None:
    response = client.get(_url(farm_id + 1), headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_member"}}


def test_requires_login(client: TestClient, farm_id: int) -> None:
    response = client.get(_url(farm_id))

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_deactivated_account_is_refused(
    client: TestClient, db, member_token: str, farm_id: int
) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.get(_url(farm_id), headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
