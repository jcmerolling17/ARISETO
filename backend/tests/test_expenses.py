"""GET /expense-categories, GET and POST /farms/{farm_id}/expenses, DELETE /expenses/{id}."""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.seasons import philippine_today, season_of
from app.models import CropCycle, Expense
from app.models.enums import CropSeason, CycleStatus
from app.services import expense_service
from tests.conftest import FarmSetup, auth_header

CATEGORY_NAMES = ["Seeds", "Fertilizer", "Chemicals", "Labor", "Equipment", "Fuel", "Others"]


def _url(farm_id: int) -> str:
    return f"/api/v1/farms/{farm_id}/expenses"


@pytest.fixture
def categories(client: TestClient, member_token: str) -> dict[str, int]:
    rows = client.get("/api/v1/expense-categories", headers=auth_header(member_token)).json()
    return {row["category_name"]: row["category_id"] for row in rows}


def _body(categories: dict[str, int], **overrides) -> dict:
    """A whole-farm Seeds expense dated today, in today's season."""
    season, year = season_of(philippine_today())
    body = {
        "category_id": categories["Seeds"],
        "amount_php": 2850.00,
        "expense_date": philippine_today().isoformat(),
        "description": "2 bags urea",
        "season": season.value,
        "season_year": year,
        "client_uuid": str(uuid.uuid4()),
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not ...}


def _post(client: TestClient, token: str, farm_id: int, body: dict):
    return client.post(_url(farm_id), json=body, headers=auth_header(token))


def _set_cycle(db, cycle_id: int, season: CropSeason, sown: date, status=CycleStatus.ACTIVE):
    cycle = db.get(CropCycle, cycle_id)
    cycle.season, cycle.planting_date, cycle.status = season, sown, status
    db.commit()


def _count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Expense))


# ---------- GET /expense-categories ----------


def test_categories_are_the_seven_in_documented_order(client: TestClient, member_token: str):
    response = client.get("/api/v1/expense-categories", headers=auth_header(member_token))

    assert response.status_code == 200
    body = response.json()
    assert [row["category_name"] for row in body] == CATEGORY_NAMES
    assert set(body[0]) == {"category_id", "category_name"}


# ---------- POST: whole farm and field ----------


def test_whole_farm_expense_is_saved_with_its_season(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    body = _body(categories, season="dry", season_year=2026, quantity=2, unit="bag")

    response = _post(client, member_token, farm.farm_id, body)

    assert response.status_code == 201
    created = response.json()
    assert created == {"expense_id": created["expense_id"], "season": "dry", "season_year": 2026}
    expense = db.get(Expense, created["expense_id"])
    assert expense.cycle_id is None
    assert expense.farm_id == farm.farm_id
    assert expense.synced_at is not None
    assert (float(expense.quantity), expense.unit) == (2.0, "bag")
    assert str(expense.client_uuid) == body["client_uuid"]


def test_field_expense_takes_season_from_its_cycle(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    _set_cycle(db, farm.cycle_ids["Field A"], CropSeason.DRY, date(2027, 1, 10))
    body = _body(categories, cycle_id=farm.cycle_ids["Field A"], season=..., season_year=...)

    response = _post(client, member_token, farm.farm_id, body)

    assert response.status_code == 201
    assert (response.json()["season"], response.json()["season_year"]) == ("dry", 2026)


@pytest.mark.parametrize(
    ("season", "sown", "expected_year"),
    [
        (CropSeason.DRY, date(2026, 12, 15), 2026),
        (CropSeason.DRY, date(2027, 1, 5), 2026),
        (CropSeason.WET, date(2027, 1, 5), 2027),
        (CropSeason.WET, date(2026, 7, 1), 2026),
    ],
)
def test_field_expense_season_year_across_december_and_january(
    client: TestClient, db, member_token, farm: FarmSetup, categories, season, sown, expected_year
):
    _set_cycle(db, farm.cycle_ids["Field A"], season, sown)
    body = _body(categories, cycle_id=farm.cycle_ids["Field A"], season=..., season_year=...)

    created = _post(client, member_token, farm.farm_id, body).json()

    assert (created["season"], created["season_year"]) == (season.value, expected_year)


def test_field_expense_may_send_its_matching_season(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    _set_cycle(db, farm.cycle_ids["Field A"], CropSeason.DRY, date(2026, 12, 15))
    body = _body(categories, cycle_id=farm.cycle_ids["Field A"], season="dry", season_year=2026)

    assert _post(client, member_token, farm.farm_id, body).status_code == 201


@pytest.mark.parametrize(
    "sent", [{"season": "wet"}, {"season_year": 2025}, {"season": "wet", "season_year": 2026}]
)
def test_field_expense_with_another_season_is_season_mismatch(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories, sent: dict
):
    _set_cycle(db, farm.cycle_ids["Field A"], CropSeason.DRY, date(2026, 12, 15))
    body = _body(categories, cycle_id=farm.cycle_ids["Field A"], season=..., season_year=...)

    response = _post(client, member_token, farm.farm_id, {**body, **sent})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "season_mismatch"}}
    assert _count(db) == 0


@pytest.mark.parametrize("status", [CycleStatus.HARVESTED, CycleStatus.FAILED])
def test_expense_on_a_closed_cycle_is_allowed(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories, status
):
    _set_cycle(db, farm.cycle_ids["Field B"], CropSeason.WET, date(2026, 7, 1), status)
    body = _body(categories, cycle_id=farm.cycle_ids["Field B"], season=..., season_year=...)

    assert _post(client, member_token, farm.farm_id, body).status_code == 201


def test_whole_farm_expense_date_need_not_fall_in_its_season(
    client: TestClient, member_token: str, farm: FarmSetup, categories
):
    body = _body(categories, expense_date="2024-03-01", season="wet", season_year=2026)

    assert _post(client, member_token, farm.farm_id, body).status_code == 201


def test_a_worker_on_the_farm_can_record_expenses(
    client: TestClient, db, worker_token: str, farm: FarmSetup, categories
):
    response = _post(client, worker_token, farm.farm_id, _body(categories))

    assert response.status_code == 201


# ---------- POST: error codes ----------


@pytest.mark.parametrize(
    "missing", [{"season": ...}, {"season_year": ...}, {"season": ..., "season_year": ...}]
)
def test_whole_farm_expense_without_its_season_is_season_required(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories, missing: dict
):
    response = _post(client, member_token, farm.farm_id, _body(categories, **missing))

    assert response.json() == {"detail": {"code": "season_required"}}
    assert _count(db) == 0


def test_unknown_category_is_category_not_found(
    client: TestClient, member_token: str, farm: FarmSetup, categories
):
    response = _post(client, member_token, farm.farm_id, _body(categories, category_id=999))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "category_not_found"}}


def test_cycle_of_another_farm_is_cycle_not_in_farm(
    client: TestClient, member_token: str, farm: FarmSetup, other_farm: FarmSetup, categories
):
    for cycle_id in (other_farm.cycle_ids["Field A"], 999999):
        body = _body(categories, cycle_id=cycle_id, season=..., season_year=...)
        response = _post(client, member_token, farm.farm_id, body)
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "cycle_not_in_farm"}}


def test_quantity_without_unit_is_unit_required(
    client: TestClient, member_token: str, farm: FarmSetup, categories
):
    response = _post(client, member_token, farm.farm_id, _body(categories, quantity=2))

    assert response.json() == {"detail": {"code": "unit_required"}}


def test_unit_without_quantity_is_quantity_required(
    client: TestClient, member_token: str, farm: FarmSetup, categories
):
    response = _post(client, member_token, farm.farm_id, _body(categories, unit="sack"))

    assert response.json() == {"detail": {"code": "quantity_required"}}


def test_date_after_philippine_today_is_expense_date_in_future(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    tomorrow = (philippine_today() + timedelta(days=1)).isoformat()

    response = _post(client, member_token, farm.farm_id, _body(categories, expense_date=tomorrow))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "expense_date_in_future"}}
    assert _count(db) == 0


def test_today_uses_the_philippine_date(
    client: TestClient, member_token: str, farm: FarmSetup, categories, monkeypatch
):
    monkeypatch.setattr(expense_service, "philippine_today", lambda: date(2026, 1, 1))

    late = _post(client, member_token, farm.farm_id, _body(categories, expense_date="2026-01-02"))
    on_time = _post(
        client, member_token, farm.farm_id, _body(categories, expense_date="2026-01-01")
    )

    assert late.json() == {"detail": {"code": "expense_date_in_future"}}
    assert on_time.status_code == 201


def test_non_member_gets_not_farm_member(
    client: TestClient, outsider_token: str, farm: FarmSetup, categories
):
    for farm_id in (farm.farm_id, 999999):
        response = _post(client, outsider_token, farm_id, _body(categories))
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "not_farm_member"}}


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_php": 0},
        {"amount_php": -5},
        {"amount_php": 1.005},
        {"amount_php": 100000000},
        {"description": "x" * 256},
        {"quantity": 0, "unit": "kg"},
        {"quantity": 2, "unit": "ton"},
        {"season": "summer"},
        {"season_year": 10000},
        {"client_uuid": "not-a-uuid"},
        {"client_uuid": ...},
        {"category_id": ...},
        {"expense_date": "06/01/2026"},
        {"recorded_by": 1},
    ],
)
def test_invalid_body_uses_fastapi_422(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories, overrides: dict
):
    response = _post(client, member_token, farm.farm_id, _body(categories, **overrides))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert _count(db) == 0


def test_blank_description_is_stored_as_none(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    created = _post(client, member_token, farm.farm_id, _body(categories, description="   ")).json()

    assert db.get(Expense, created["expense_id"]).description is None


# ---------- POST: client_uuid repeat ----------


def test_repeat_by_the_same_caller_returns_the_saved_expense(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    body = _body(categories)
    first = _post(client, member_token, farm.farm_id, body)

    again = _post(client, member_token, farm.farm_id, {**body, "amount_php": 999})

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == first.json()
    assert _count(db) == 1
    assert float(db.get(Expense, first.json()["expense_id"]).amount_php) == 2850.0


def test_uuid_saved_by_another_member_is_client_uuid_taken(
    client: TestClient, db, member_token: str, worker_token: str, farm: FarmSetup, categories
):
    body = _body(categories)
    _post(client, member_token, farm.farm_id, body)

    response = _post(client, worker_token, farm.farm_id, body)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "client_uuid_taken"}}
    assert _count(db) == 1


def test_uuid_saved_on_another_farm_is_client_uuid_taken(
    client: TestClient,
    db,
    outsider_token: str,
    other_farm: FarmSetup,
    member_token: str,
    farm: FarmSetup,
    categories,
):
    body = _body(categories)
    _post(client, outsider_token, other_farm.farm_id, body)

    response = _post(client, member_token, farm.farm_id, body)

    assert response.json() == {"detail": {"code": "client_uuid_taken"}}


# ---------- GET /farms/{farm_id}/expenses ----------


def _list(client: TestClient, token: str, farm_id: int, **params):
    return client.get(_url(farm_id), params=params, headers=auth_header(token))


def test_list_is_newest_first_with_names_and_delete_rights(
    client: TestClient, db, member_token: str, worker_token: str, farm: FarmSetup, categories
):
    _set_cycle(db, farm.cycle_ids["Field A"], CropSeason.WET, date(2026, 7, 1))
    season = {"season": "wet", "season_year": 2026}
    owners = _post(
        client,
        member_token,
        farm.farm_id,
        _body(
            categories,
            expense_date="2026-07-05",
            cycle_id=farm.cycle_ids["Field A"],
            category_id=categories["Fertilizer"],
            **season,
        ),
    ).json()
    workers = _post(
        client,
        worker_token,
        farm.farm_id,
        _body(categories, expense_date="2026-07-05", quantity=3, unit="sack", **season),
    ).json()
    older = _post(
        client, member_token, farm.farm_id, _body(categories, expense_date="2026-06-20", **season)
    ).json()

    as_worker = _list(client, worker_token, farm.farm_id, **season).json()

    assert [row["expense_id"] for row in as_worker] == [
        workers["expense_id"],
        owners["expense_id"],
        older["expense_id"],
    ]
    first, second, _ = as_worker
    assert first == {
        "expense_id": workers["expense_id"],
        "category_id": categories["Seeds"],
        "category_name": "Seeds",
        "amount_php": 2850.0,
        "expense_date": "2026-07-05",
        "description": "2 bags urea",
        "quantity": 3.0,
        "unit": "sack",
        "cycle_id": None,
        "field_name": None,
        "season": "wet",
        "season_year": 2026,
        "recorded_by_name": "Pedro Reyes",
        "can_delete": True,
    }
    assert second["field_name"] == "Field A"
    assert second["category_name"] == "Fertilizer"
    assert second["recorded_by_name"] == "Ma. Cristina Dela Cruz"
    assert second["can_delete"] is False  # the owner's expense, seen by the worker
    as_owner = _list(client, member_token, farm.farm_id, **season).json()
    assert all(row["can_delete"] for row in as_owner)


def test_list_defaults_to_the_current_philippine_season(
    client: TestClient, member_token: str, farm: FarmSetup, categories, monkeypatch
):
    monkeypatch.setattr(expense_service, "philippine_today", lambda: date(2027, 1, 15))
    current = _post(
        client,
        member_token,
        farm.farm_id,
        _body(categories, expense_date="2027-01-10", season="dry", season_year=2026),
    ).json()
    _post(
        client,
        member_token,
        farm.farm_id,
        _body(categories, expense_date="2026-10-10", season="wet", season_year=2026),
    )

    rows = _list(client, member_token, farm.farm_id).json()

    assert [row["expense_id"] for row in rows] == [current["expense_id"]]


def test_field_filter_shows_only_that_fields_expenses(
    client: TestClient, db, member_token: str, farm: FarmSetup, categories
):
    for name in ("Field A", "Field B"):
        _set_cycle(db, farm.cycle_ids[name], CropSeason.WET, date(2026, 7, 1))
    season = {"season": "wet", "season_year": 2026}
    field_a = _post(
        client,
        member_token,
        farm.farm_id,
        _body(categories, cycle_id=farm.cycle_ids["Field A"], expense_date="2026-07-02", **season),
    ).json()
    _post(
        client,
        member_token,
        farm.farm_id,
        _body(categories, cycle_id=farm.cycle_ids["Field B"], expense_date="2026-07-02", **season),
    )
    _post(
        client, member_token, farm.farm_id, _body(categories, expense_date="2026-07-02", **season)
    )

    rows = _list(
        client, member_token, farm.farm_id, field_id=farm.field_ids["Field A"], **season
    ).json()

    assert [row["expense_id"] for row in rows] == [field_a["expense_id"]]


@pytest.mark.parametrize("params", [{"season": "wet"}, {"season_year": 2026}])
def test_list_with_half_a_season_is_season_incomplete(
    client: TestClient, member_token: str, farm: FarmSetup, params: dict
):
    response = _list(client, member_token, farm.farm_id, **params)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "season_incomplete"}}


def test_list_with_another_farms_field_is_field_not_in_farm(
    client: TestClient, member_token: str, farm: FarmSetup, other_farm: FarmSetup
):
    for field_id in (other_farm.field_ids["Field A"], 999999):
        response = _list(client, member_token, farm.farm_id, field_id=field_id)
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "field_not_in_farm"}}


def test_list_by_a_non_member_is_not_farm_member(
    client: TestClient, outsider_token: str, farm: FarmSetup
):
    response = _list(client, outsider_token, farm.farm_id)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_member"}}


@pytest.mark.parametrize("params", [{"season": "summer", "season_year": 2026}, {"field_id": "x"}])
def test_list_with_bad_query_uses_fastapi_422(
    client: TestClient, member_token: str, farm: FarmSetup, params: dict
):
    response = _list(client, member_token, farm.farm_id, **params)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# ---------- DELETE /expenses/{expense_id} ----------


def _delete(client: TestClient, token: str, expense_id: int):
    return client.delete(f"/api/v1/expenses/{expense_id}", headers=auth_header(token))


def test_the_recorder_can_delete_their_expense(
    client: TestClient, db, worker_token: str, farm: FarmSetup, categories
):
    expense_id = _post(client, worker_token, farm.farm_id, _body(categories)).json()["expense_id"]

    response = _delete(client, worker_token, expense_id)

    assert response.status_code == 204
    assert response.content == b""
    assert _count(db) == 0


def test_the_owner_can_delete_a_workers_expense(
    client: TestClient, db, member_token: str, worker_token: str, farm: FarmSetup, categories
):
    expense_id = _post(client, worker_token, farm.farm_id, _body(categories)).json()["expense_id"]

    assert _delete(client, member_token, expense_id).status_code == 204
    assert _count(db) == 0


def test_a_worker_cannot_delete_the_owners_expense(
    client: TestClient, db, member_token: str, worker_token: str, farm: FarmSetup, categories
):
    expense_id = _post(client, member_token, farm.farm_id, _body(categories)).json()["expense_id"]

    response = _delete(client, worker_token, expense_id)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_allowed"}}
    assert _count(db) == 1


def test_delete_by_a_non_member_or_of_a_missing_expense_is_not_found(
    client: TestClient, db, member_token: str, outsider_token: str, farm: FarmSetup, categories
):
    expense_id = _post(client, member_token, farm.farm_id, _body(categories)).json()["expense_id"]

    for token, target in ((outsider_token, expense_id), (member_token, 999999)):
        response = _delete(client, token, target)
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "expense_not_found"}}
    assert _count(db) == 1
