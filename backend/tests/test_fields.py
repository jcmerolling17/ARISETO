from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.constants import PLANTING_WINDOW_DAYS
from app.models import Barangay, Crop, FarmField
from tests.conftest import MEMBER_PASSWORD, auth_header, create_active_member, login_token


@pytest.fixture
def farm_id(client: TestClient, db, member_token: str) -> int:
    """A 2.75 ha farm owned by the member behind member_token."""
    barangay = Barangay(
        psgc_code="1704106010",
        municipality="Mamburao",
        barangay_name="Tangkalan",
        center_latitude=13.2,
        center_longitude=120.6,
    )
    db.add(barangay)
    db.commit()
    body = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay.barangay_id,
        "latitude": 13.2,
        "longitude": 120.6,
        "total_area_ha": 2.75,
    }
    return client.post("/api/v1/farms", json=body, headers=auth_header(member_token)).json()[
        "farm_id"
    ]


def _url(farm_id: int) -> str:
    return f"/api/v1/farms/{farm_id}/fields"


def field_payload(**overrides: object) -> dict:
    """A valid POST /farms/{farm_id}/fields body, as js/api/client.js sends it."""
    payload = {
        "field_name": "Field A",
        "crop": "corn",
        "variety": "Pioneer 30W",
        "area_ha": 1.25,
        "planting_date": date.today().isoformat(),
        "planting_method": "direct_seeding",
        "season": "dry",
    }
    payload.update(overrides)
    return payload


def test_migration_seeds_the_three_crops(db) -> None:
    names = db.scalars(select(Crop.crop_name).order_by(Crop.crop_name)).all()

    assert names == ["Corn", "Onion", "Rice"]


def test_adds_fields_until_the_farm_area_is_used(
    client: TestClient, db, member_token: str, farm_id: int
) -> None:
    first = client.post(_url(farm_id), json=field_payload(), headers=auth_header(member_token))
    second = client.post(
        _url(farm_id),
        json=field_payload(
            field_name="Field B",
            crop="rice",
            variety="NSIC Rc222",
            area_ha=1.5,
            planting_method="transplanting",
        ),
        headers=auth_header(member_token),
    )

    assert first.status_code == 201
    assert first.json() == {
        "field_id": first.json()["field_id"],
        "farm_id": farm_id,
        "field_name": "Field A",
        "crop": "corn",
        "variety": "Pioneer 30W",
        "area_ha": 1.25,
        "planting_date": date.today().isoformat(),
        "planting_method": "direct_seeding",
        "season": "dry",
    }
    assert second.status_code == 201
    stored = db.scalars(select(FarmField).order_by(FarmField.field_id)).all()
    assert [(f.field_name, f.variety_name) for f in stored] == [
        ("Field A", "Pioneer 30W"),
        ("Field B", "NSIC Rc222"),
    ]


def test_area_cannot_exceed_the_farm(client: TestClient, member_token: str, farm_id: int) -> None:
    client.post(_url(farm_id), json=field_payload(area_ha=2), headers=auth_header(member_token))

    response = client.post(
        _url(farm_id),
        json=field_payload(field_name="Field B", area_ha=0.7501),
        headers=auth_header(member_token),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "area_exceeds_farm"}}


@pytest.mark.parametrize("name", ["Field A", "field a", "  FIELD   A "])
def test_field_names_are_unique_per_farm_ignoring_case(
    client: TestClient, member_token: str, farm_id: int, name: str
) -> None:
    client.post(_url(farm_id), json=field_payload(area_ha=1), headers=auth_header(member_token))

    response = client.post(
        _url(farm_id),
        json=field_payload(field_name=name, area_ha=1),
        headers=auth_header(member_token),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "field_name_taken"}}


@pytest.mark.parametrize("days", [PLANTING_WINDOW_DAYS + 1, -(PLANTING_WINDOW_DAYS + 1)])
def test_planting_date_window(
    client: TestClient, member_token: str, farm_id: int, days: int
) -> None:
    planted = (date.today() + timedelta(days=days)).isoformat()
    response = client.post(
        _url(farm_id), json=field_payload(planting_date=planted), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "planting_date_out_of_range"}}


def test_only_the_owner_can_add_fields(
    client: TestClient, db, member_token: str, farm_id: int
) -> None:
    create_active_member(
        db, mobile_no="+639171111111", email="pedro@example.com", member_no="MPMPC-0043"
    )
    other = login_token(client, "+639171111111", MEMBER_PASSWORD)

    response = client.post(_url(farm_id), json=field_payload(), headers=auth_header(other))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_owner"}}
    assert db.scalar(select(FarmField)) is None


def test_unknown_farm(client: TestClient, member_token: str, farm_id: int) -> None:
    response = client.post(
        _url(farm_id + 1), json=field_payload(), headers=auth_header(member_token)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "farm_not_found"}}


def test_requires_login(client: TestClient, farm_id: int) -> None:
    response = client.post(_url(farm_id), json=field_payload())

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


@pytest.mark.parametrize(
    "overrides",
    [
        {"field_name": ""},
        {"field_name": "x" * 51},
        {"crop": "wheat"},
        {"crop": "Rice"},
        {"variety": " "},
        {"area_ha": 0},
        {"area_ha": 0.00001},
        {"planting_date": "10/02/2026"},
        {"planting_method": "broadcasting"},
        {"season": "summer"},
        {"variety_id": 1},
    ],
)
def test_rejects_invalid_body(
    client: TestClient, member_token: str, farm_id: int, overrides: dict
) -> None:
    response = client.post(
        _url(farm_id), json=field_payload(**overrides), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
