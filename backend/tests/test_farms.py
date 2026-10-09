import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Barangay, Farm, FarmAssignment, User
from app.models.enums import AccountStatus, FarmRole
from tests.conftest import auth_header

URL = "/api/v1/farms"


@pytest.fixture
def barangay_id(db) -> int:
    barangay = Barangay(
        psgc_code="1704106010",
        municipality="Mamburao",
        barangay_name="Tangkalan",
        center_latitude=13.2,
        center_longitude=120.6,
    )
    db.add(barangay)
    db.commit()
    return barangay.barangay_id


def farm_payload(barangay_id: int, **overrides: object) -> dict:
    """A valid POST /farms body, as the farm setup review step sends it."""
    payload = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "latitude": 13.2,
        "longitude": 120.6,
        "total_area_ha": 2.75,
    }
    payload.update(overrides)
    return payload


def test_creates_farm_and_makes_caller_owner(
    client: TestClient, db, member_token: str, barangay_id: int
) -> None:
    response = client.post(URL, json=farm_payload(barangay_id), headers=auth_header(member_token))

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "farm_id": body["farm_id"],
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "latitude": 13.2,
        "longitude": 120.6,
        "total_area_ha": 2.75,
    }
    owner = db.scalar(select(FarmAssignment).where(FarmAssignment.farm_id == body["farm_id"]))
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    assert owner.user_id == member.user_id
    assert owner.role_on_farm == FarmRole.OWNER


def test_collapses_spaces_in_farm_name(
    client: TestClient, db, member_token: str, barangay_id: int
) -> None:
    payload = farm_payload(barangay_id, farm_name="  MPMPC   Farm ")
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.json()["farm_name"] == "MPMPC Farm"


def test_requires_login(client: TestClient, barangay_id: int) -> None:
    response = client.post(URL, json=farm_payload(barangay_id))

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_deactivated_account_is_refused(
    client: TestClient, db, member_token: str, barangay_id: int
) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.post(URL, json=farm_payload(barangay_id), headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
    assert db.scalar(select(Farm)) is None


def test_unknown_barangay(client: TestClient, member_token: str, barangay_id: int) -> None:
    payload = farm_payload(barangay_id + 1)
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "barangay_not_found"}}


@pytest.mark.parametrize(("latitude", "longitude"), [(14.6, 121.0), (13.2, 122.0), (11.9, 120.6)])
def test_coordinates_outside_province(
    client: TestClient, db, member_token: str, barangay_id: int, latitude: float, longitude: float
) -> None:
    payload = farm_payload(barangay_id, latitude=latitude, longitude=longitude)
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "coordinates_outside_province"}}
    assert db.scalar(select(Farm)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"farm_name": "   "},
        {"farm_name": "x" * 101},
        {"total_area_ha": 0},
        {"total_area_ha": 1.23456},
        {"total_area_ha": 1000000},
        {"latitude": 13.1234567},
        {"owner_id": 1},
    ],
)
def test_rejects_invalid_body(
    client: TestClient, member_token: str, barangay_id: int, overrides: dict
) -> None:
    payload = farm_payload(barangay_id, **overrides)
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
