from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import (
    CalendarTemplateTask,
    CropActivity,
    CropCycle,
    Farm,
    FarmAssignment,
    FarmField,
    User,
)
from app.models.enums import AccountStatus, ActivityStatus, CycleStatus, FarmRole, TaskType
from app.services.farm_service import planting_window
from tests.conftest import auth_header

URL = "/api/v1/farms"


def setup_field(variety_id: int, **overrides: object) -> dict:
    """One field of a POST /farms body."""
    field = {
        "field_name": "Field A",
        "area_ha": 1.25,
        "variety_id": variety_id,
        "planting_date": date.today().isoformat(),
    }
    field.update(overrides)
    return field


def farm_payload(barangay_id: int, fields: list[dict], **overrides: object) -> dict:
    """A valid POST /farms body, as the farm setup review step sends it."""
    payload = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "season": "wet",
        "fields": fields,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def two_fields(variety_ids: dict[str, int]) -> list[dict]:
    """Corn sown today and rice sown in 10 days."""
    return [
        setup_field(variety_ids["NK6410"]),
        setup_field(
            variety_ids["RC-402"],
            field_name="Field B",
            area_ha=1.5,
            planting_date=(date.today() + timedelta(days=10)).isoformat(),
        ),
    ]


def saved_rows(db) -> dict[str, int]:
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model))
        for model in (Farm, FarmAssignment, FarmField, CropCycle, CropActivity)
    }


NOTHING_SAVED = {
    "farm": 0,
    "farm_assignment": 0,
    "field": 0,
    "crop_cycle": 0,
    "crop_activity": 0,
}


def test_saves_farm_fields_and_first_cycles(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict]
) -> None:
    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    assert response.status_code == 201
    body = response.json()
    fields = db.scalars(select(FarmField).order_by(FarmField.field_id)).all()
    cycles = db.scalars(select(CropCycle).order_by(CropCycle.cycle_id)).all()
    today = date.today()
    assert body == {
        "farm_id": body["farm_id"],
        "total_area_ha": 2.75,
        "fields": [
            {
                "field_id": fields[0].field_id,
                "cycle_id": cycles[0].cycle_id,
                "expected_harvest_date": (today + timedelta(days=90)).isoformat(),
            },
            {
                "field_id": fields[1].field_id,
                "cycle_id": cycles[1].cycle_id,
                "expected_harvest_date": (today + timedelta(days=120)).isoformat(),
            },
        ],
    }
    farm = db.get(Farm, body["farm_id"])
    assert (farm.latitude, farm.longitude, farm.total_area_ha) == (
        Decimal("13.271995"),
        Decimal("120.624727"),
        Decimal("2.7500"),
    )
    assert [(f.farm_id, f.field_name, f.area_ha) for f in fields] == [
        (farm.farm_id, "Field A", Decimal("1.2500")),
        (farm.farm_id, "Field B", Decimal("1.5000")),
    ]
    assert [
        (c.field_id, c.season, c.area_planted_ha, c.planting_date, c.status) for c in cycles
    ] == [
        (fields[0].field_id, "wet", Decimal("1.2500"), today, CycleStatus.ACTIVE),
        (fields[1].field_id, "wet", Decimal("1.5000"), today + timedelta(days=10), "planned"),
    ]
    owner = db.scalar(select(FarmAssignment).where(FarmAssignment.farm_id == farm.farm_id))
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    assert (owner.user_id, owner.role_on_farm) == (member.user_id, FarmRole.OWNER)
    # No calendar templates exist yet, so no activities are scheduled.
    assert saved_rows(db)["crop_activity"] == 0


def test_schedules_calendar_from_template_tasks(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict], variety_ids
) -> None:
    # Templates made only for this test; the seed data has none.
    corn = variety_ids["NK6410"]
    db.add_all(
        [
            CalendarTemplateTask(
                variety_id=corn,
                week_no=3,
                task_type=TaskType.FERTILIZATION,
                task_name="Side-dress fertilizer",
                is_weather_sensitive=True,
            ),
            CalendarTemplateTask(
                variety_id=corn,
                week_no=-1,
                task_type=TaskType.LAND_PREP,
                task_name="Prepare the land",
                is_weather_sensitive=False,
            ),
        ]
    )
    db.commit()

    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    corn_cycle = response.json()["fields"][0]["cycle_id"]
    activities = db.scalars(select(CropActivity).order_by(CropActivity.scheduled_date)).all()
    today = date.today()
    assert [
        (a.cycle_id, a.title, a.scheduled_date, a.status, a.completed_at) for a in activities
    ] == [
        (corn_cycle, "Prepare the land", today - timedelta(weeks=1), ActivityStatus.PENDING, None),
        (corn_cycle, "Side-dress fertilizer", today + timedelta(weeks=3), "pending", None),
    ]
    assert all(a.template_task_id is not None for a in activities)
    assert activities[0].client_uuid != activities[1].client_uuid


def test_coop_admin_can_create_a_farm(
    client: TestClient, admin_token: str, barangay_id: int, two_fields: list[dict]
) -> None:
    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(admin_token)
    )

    assert response.status_code == 201


def test_collapses_spaces_in_names(
    client: TestClient, db, member_token: str, barangay_id: int, variety_ids
) -> None:
    fields = [setup_field(variety_ids["NK6410"], field_name="  Lower   paddy ")]
    payload = farm_payload(barangay_id, fields, farm_name="  MPMPC   Farm ")
    client.post(URL, json=payload, headers=auth_header(member_token))

    assert db.scalar(select(Farm.farm_name)) == "MPMPC Farm"
    assert db.scalar(select(FarmField.field_name)) == "Lower paddy"


def test_requires_login(client: TestClient, barangay_id: int, two_fields: list[dict]) -> None:
    response = client.post(URL, json=farm_payload(barangay_id, two_fields))

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_deactivated_account_is_refused(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict]
) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
    assert saved_rows(db) == NOTHING_SAVED


def test_no_fields(client: TestClient, db, member_token: str, barangay_id: int) -> None:
    response = client.post(
        URL, json=farm_payload(barangay_id, []), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "no_fields"}}
    assert saved_rows(db) == NOTHING_SAVED


@pytest.mark.parametrize("name", ["Field A", "field a", "  FIELD   A "])
def test_field_names_must_differ_within_the_request(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict], name: str
) -> None:
    two_fields[1]["field_name"] = name
    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "field_name_taken"}}
    assert saved_rows(db) == NOTHING_SAVED


def test_unknown_barangay(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict]
) -> None:
    payload = farm_payload(barangay_id + 1, two_fields)
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "barangay_not_found"}}
    assert saved_rows(db) == NOTHING_SAVED


@pytest.mark.parametrize("edge", ["first", "last"])
def test_planting_date_window(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict], edge: str
) -> None:
    first, last = planting_window(date.today())
    inside = first if edge == "first" else last
    outside = first - timedelta(days=1) if edge == "first" else last + timedelta(days=1)

    two_fields[1]["planting_date"] = outside.isoformat()
    refused = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )
    assert refused.status_code == 422
    assert refused.json() == {"detail": {"code": "planting_date_out_of_range"}}
    assert saved_rows(db) == NOTHING_SAVED

    two_fields[1]["planting_date"] = inside.isoformat()
    accepted = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )
    assert accepted.status_code == 201


@pytest.mark.parametrize(
    ("today", "window"),
    [
        (date(2026, 10, 14), (date(2024, 10, 14), date(2028, 10, 14))),
        (date(2028, 2, 29), (date(2026, 2, 28), date(2030, 2, 28))),
        (date(2026, 2, 28), (date(2024, 2, 28), date(2028, 2, 28))),
    ],
)
def test_planting_window_is_two_calendar_years(today: date, window: tuple[date, date]) -> None:
    assert planting_window(today) == window


def test_unknown_variety_saves_nothing(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict], variety_ids
) -> None:
    two_fields[1]["variety_id"] = max(variety_ids.values()) + 1
    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "variety_not_found"}}
    assert saved_rows(db) == NOTHING_SAVED


@pytest.mark.parametrize(
    "overrides",
    [
        {"farm_name": "   "},
        {"farm_name": "x" * 101},
        {"season": "summer"},
        {"fields": None},
        {"fields": "Field A"},
        {"latitude": 13.2},
        {"total_area_ha": 2.75},
    ],
)
def test_rejects_invalid_body(
    client: TestClient, member_token: str, barangay_id: int, two_fields: list[dict], overrides
) -> None:
    payload = farm_payload(barangay_id, two_fields)
    payload.update(overrides)
    response = client.post(URL, json=payload, headers=auth_header(member_token))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    "overrides",
    [
        {"field_name": ""},
        {"field_name": "x" * 51},
        {"area_ha": 0},
        {"area_ha": 0.00001},
        {"variety_id": "NK6410"},
        {"planting_date": "10/02/2026"},
        {"planting_method": "direct_seeding"},
        {"season": "wet"},
    ],
)
def test_rejects_invalid_field(
    client: TestClient, db, member_token: str, barangay_id: int, two_fields: list[dict], overrides
) -> None:
    two_fields[1].update(overrides)
    response = client.post(
        URL, json=farm_payload(barangay_id, two_fields), headers=auth_header(member_token)
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert saved_rows(db) == NOTHING_SAVED


def test_lists_the_callers_farms_oldest_first(
    client: TestClient, db, member_token: str, admin_token: str, barangay_id: int, variety_ids
) -> None:
    corn = variety_ids["NK6410"]
    for name in ("First Farm", "Second Farm"):
        payload = farm_payload(barangay_id, [setup_field(corn)], farm_name=name)
        client.post(URL, json=payload, headers=auth_header(member_token))
    admin_farm = farm_payload(barangay_id, [setup_field(corn)], farm_name="Admin Farm")
    admin_farm_id = client.post(URL, json=admin_farm, headers=auth_header(admin_token)).json()[
        "farm_id"
    ]
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    db.add(FarmAssignment(farm_id=admin_farm_id, user_id=member.user_id, role_on_farm="worker"))
    db.commit()

    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 200
    farms = response.json()
    assert [(f["farm_name"], f["role_on_farm"]) for f in farms] == [
        ("First Farm", "owner"),
        ("Second Farm", "owner"),
        ("Admin Farm", "worker"),
    ]
    assert farms[0] == {
        "farm_id": farms[0]["farm_id"],
        "farm_name": "First Farm",
        "barangay_id": barangay_id,
        "barangay_name": "Tangkalan",
        "municipality": "Mamburao",
        "latitude": 13.271995,
        "longitude": 120.624727,
        "total_area_ha": 1.25,
        "role_on_farm": "owner",
    }


def test_lists_no_farms_before_setup(client: TestClient, member_token: str) -> None:
    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 200
    assert response.json() == []


def test_listing_requires_login(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_listing_refuses_a_deactivated_account(client: TestClient, db, member_token: str) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
