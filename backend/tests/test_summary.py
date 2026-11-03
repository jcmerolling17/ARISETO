"""GET /farms/{farm_id}/summary: season totals and net profit, computed on request."""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models import CropCycle
from app.models.enums import CropSeason
from app.services import harvest_service
from tests.conftest import FarmSetup, auth_header

WET_2026 = {"season": "wet", "season_year": 2026}
CATEGORY_NAMES = ["Seeds", "Fertilizer", "Chemicals", "Labor", "Equipment", "Fuel", "Others"]


@pytest.fixture
def categories(client: TestClient, member_token: str) -> dict[str, int]:
    rows = client.get("/api/v1/expense-categories", headers=auth_header(member_token)).json()
    return {row["category_name"]: row["category_id"] for row in rows}


@pytest.fixture
def wet_2026(db, farm: FarmSetup, monkeypatch) -> FarmSetup:
    """Both cycles sown in the 2026 wet season; 'today' is in October 2026."""
    for cycle_id in farm.cycle_ids.values():
        cycle = db.get(CropCycle, cycle_id)
        cycle.season, cycle.planting_date = CropSeason.WET, date(2026, 6, 15)
    db.commit()
    monkeypatch.setattr(harvest_service, "philippine_today", lambda: date(2026, 10, 1))
    return farm


def _expense(client, token, farm: FarmSetup, categories, category, amount, field=None, **season):
    body = {
        "category_id": categories[category],
        "amount_php": amount,
        "expense_date": "2026-07-01",
        "client_uuid": str(uuid.uuid4()),
    }
    if field is None:
        body.update(season or WET_2026)
    else:
        body["cycle_id"] = farm.cycle_ids[field]
    response = client.post(
        f"/api/v1/farms/{farm.farm_id}/expenses", json=body, headers=auth_header(token)
    )
    assert response.status_code == 201, response.json()


def _harvest(client, token, farm: FarmSetup, field, kg, price):
    body = {
        "harvest_date": "2026-09-15",
        "quantity_kg": kg,
        "unit_price_php": price,
        "final_harvest": False,
    }
    response = client.post(
        f"/api/v1/cycles/{farm.cycle_ids[field]}/harvests", json=body, headers=auth_header(token)
    )
    assert response.status_code == 201, response.json()


def _summary(client, token, farm_id, **params):
    return client.get(f"/api/v1/farms/{farm_id}/summary", params=params, headers=auth_header(token))


def test_summary_totals_categories_income_and_net_profit(
    client: TestClient, member_token: str, worker_token: str, wet_2026: FarmSetup, categories
):
    farm = wet_2026
    _expense(client, member_token, farm, categories, "Seeds", 9800, field="Field A")
    _expense(client, worker_token, farm, categories, "Fertilizer", 7000.50, field="Field B")
    _expense(client, member_token, farm, categories, "Others", 600)  # whole farm
    _expense(client, member_token, farm, categories, "Labor", 999, season="dry", season_year=2026)
    _harvest(client, member_token, farm, "Field A", 5000, 17)

    response = _summary(client, worker_token, farm.farm_id, **WET_2026)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "season": "wet",
        "season_year": 2026,
        "total_expenses_php": 17400.5,
        "whole_farm_expenses_php": 600.0,
        "by_category": [
            {"category_name": "Seeds", "amount_php": 9800.0},
            {"category_name": "Fertilizer", "amount_php": 7000.5},
            {"category_name": "Chemicals", "amount_php": 0.0},
            {"category_name": "Labor", "amount_php": 0.0},
            {"category_name": "Equipment", "amount_php": 0.0},
            {"category_name": "Fuel", "amount_php": 0.0},
            {"category_name": "Others", "amount_php": 600.0},
        ],
        "gross_income_php": 85000.0,
        "net_profit_php": 67599.5,
    }


def test_field_filter_leaves_out_whole_farm_expenses(
    client: TestClient, member_token: str, wet_2026: FarmSetup, categories
):
    farm = wet_2026
    _expense(client, member_token, farm, categories, "Seeds", 9800, field="Field A")
    _expense(client, member_token, farm, categories, "Seeds", 3800, field="Field B")
    _expense(client, member_token, farm, categories, "Others", 600)
    _harvest(client, member_token, farm, "Field A", 100, 10)
    _harvest(client, member_token, farm, "Field B", 200, 10)

    body = _summary(
        client, member_token, farm.farm_id, field_id=farm.field_ids["Field B"], **WET_2026
    ).json()

    assert body["total_expenses_php"] == 3800.0
    assert body["whole_farm_expenses_php"] == 0.0
    assert body["gross_income_php"] == 2000.0
    assert body["net_profit_php"] == -1800.0
    assert [row["category_name"] for row in body["by_category"]] == CATEGORY_NAMES


def test_an_empty_season_is_all_zero(client: TestClient, member_token: str, farm: FarmSetup):
    body = _summary(client, member_token, farm.farm_id, season="dry", season_year=2020).json()

    assert body["total_expenses_php"] == 0
    assert body["gross_income_php"] == 0
    assert body["net_profit_php"] == 0
    assert [row["amount_php"] for row in body["by_category"]] == [0.0] * 7


def test_summary_defaults_to_the_current_philippine_season(
    client: TestClient, member_token: str, farm: FarmSetup, monkeypatch
):
    from app.services import expense_service

    monkeypatch.setattr(expense_service, "philippine_today", lambda: date(2026, 12, 3))

    body = _summary(client, member_token, farm.farm_id).json()

    assert (body["season"], body["season_year"]) == ("dry", 2026)


def test_summary_errors(
    client: TestClient,
    member_token: str,
    outsider_token: str,
    farm: FarmSetup,
    other_farm: FarmSetup,
):
    assert _summary(client, outsider_token, farm.farm_id).json() == {
        "detail": {"code": "not_farm_member"}
    }
    assert _summary(client, member_token, farm.farm_id, season_year=2026).json() == {
        "detail": {"code": "season_incomplete"}
    }
    assert _summary(
        client, member_token, farm.farm_id, field_id=other_farm.field_ids["Field B"]
    ).json() == {"detail": {"code": "field_not_in_farm"}}
