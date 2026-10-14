from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Crop, CropCycle, Farm, FarmField, User
from app.models.enums import AccountStatus, CycleStatus
from app.services.farm_service import planting_window
from tests.conftest import MEMBER_PASSWORD, auth_header, create_active_member, login_token


@pytest.fixture
def farm_id(client: TestClient, member_token: str, barangay_id: int, variety_ids) -> int:
    """A farm owned by the member behind member_token, with one 1.25 ha corn field."""
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


@pytest.fixture
def payload(variety_ids) -> dict:
    """A valid POST /farms/{farm_id}/fields body: rice sown today."""
    return {
        "field_name": "Field B",
        "area_ha": 1.5,
        "variety_id": variety_ids["RC-402"],
        "season": "dry",
        "planting_date": date.today().isoformat(),
    }


def _url(farm_id: int) -> str:
    return f"/api/v1/farms/{farm_id}/fields"


def _field_count(db) -> int:
    return db.scalar(select(func.count()).select_from(FarmField))


def test_migration_seeds_the_three_crops(db) -> None:
    names = db.scalars(select(Crop.crop_name).order_by(Crop.crop_name)).all()

    assert names == ["Corn", "Onion", "Rice"]


def test_adds_field_with_first_cycle_and_grows_the_farm(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict
) -> None:
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 201
    field = db.scalar(select(FarmField).where(FarmField.field_name == "Field B"))
    cycle = db.scalar(select(CropCycle).where(CropCycle.field_id == field.field_id))
    today = date.today()
    assert response.json() == {
        "field_id": field.field_id,
        "cycle_id": cycle.cycle_id,
        "expected_harvest_date": (today + timedelta(days=110)).isoformat(),
        "total_area_ha": 2.75,
    }
    assert (field.farm_id, field.area_ha) == (farm_id, Decimal("1.5000"))
    assert (cycle.season, cycle.area_planted_ha, cycle.status, cycle.target_yield_t_ha) == (
        "dry",
        Decimal("1.5000"),
        CycleStatus.ACTIVE,
        None,
    )
    assert db.get(Farm, farm_id).total_area_ha == Decimal("2.7500")


def test_future_sowing_opens_a_planned_cycle_with_target(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict, variety_ids
) -> None:
    sown = date.today() + timedelta(days=30)
    payload.update(
        variety_id=variety_ids["C4-GREEN"], planting_date=sown.isoformat(), target_yield_t_ha=5.5
    )
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.json()["expected_harvest_date"] == (sown + timedelta(days=100)).isoformat()
    cycle = db.get(CropCycle, response.json()["cycle_id"])
    assert (cycle.status, cycle.target_yield_t_ha) == (CycleStatus.PLANNED, Decimal("5.50"))


@pytest.mark.parametrize("name", ["Field A", "field a", "  FIELD   A "])
def test_field_names_are_unique_per_farm_ignoring_case(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict, name: str
) -> None:
    payload["field_name"] = name
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "field_name_taken"}}
    assert _field_count(db) == 1


@pytest.mark.parametrize("edge", ["first", "last"])
def test_planting_date_window(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict, edge: str
) -> None:
    first, last = planting_window(date.today())
    outside = first - timedelta(days=1) if edge == "first" else last + timedelta(days=1)
    payload["planting_date"] = outside.isoformat()
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "planting_date_out_of_range"}}
    assert _field_count(db) == 1

    payload["planting_date"] = (first if edge == "first" else last).isoformat()
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))
    assert response.status_code == 201


def test_unknown_variety(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict, variety_ids
) -> None:
    payload["variety_id"] = max(variety_ids.values()) + 1
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "variety_not_found"}}
    assert _field_count(db) == 1
    assert db.get(Farm, farm_id).total_area_ha == Decimal("1.2500")


def test_only_the_owner_can_add_fields(
    client: TestClient, db, member_token: str, admin_token: str, farm_id: int, payload: dict
) -> None:
    create_active_member(
        db, mobile_no="+639171111111", email="pedro@example.com", member_no="MPMPC-0043"
    )
    other = login_token(client, "+639171111111", MEMBER_PASSWORD)

    for token in (other, admin_token):
        response = client.post(_url(farm_id), json=payload, headers=auth_header(token))
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "not_farm_owner"}}
    assert _field_count(db) == 1


def test_unknown_farm(client: TestClient, member_token: str, farm_id: int, payload: dict) -> None:
    response = client.post(_url(farm_id + 1), json=payload, headers=auth_header(member_token))

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "farm_not_found"}}


def test_requires_login(client: TestClient, farm_id: int, payload: dict) -> None:
    response = client.post(_url(farm_id), json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_deactivated_account_is_refused(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict
) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}


@pytest.mark.parametrize(
    "overrides",
    [
        {"field_name": ""},
        {"field_name": "x" * 51},
        {"area_ha": 0},
        {"area_ha": 0.00001},
        {"variety_id": None},
        {"planting_date": "10/02/2026"},
        {"season": "summer"},
        {"target_yield_t_ha": 0},
        {"target_yield_t_ha": 5.555},
        {"target_yield_t_ha": 10000},
        {"planting_method": "direct_seeding"},
        {"crop": "corn"},
    ],
)
def test_rejects_invalid_body(
    client: TestClient, db, member_token: str, farm_id: int, payload: dict, overrides: dict
) -> None:
    payload.update(overrides)
    response = client.post(_url(farm_id), json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert _field_count(db) == 1
