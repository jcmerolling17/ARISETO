"""GET /farms/{farm_id}/report (DFD 7.5, Phase 13): per crop cycle and in total, computed on
request; the totals match GET /farms/{farm_id}/summary. Made-up test data."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Crop, CropActivity, CropCycle, CropVariety, Diagnosis, Disease, User
from app.models.enums import ActivityStatus, CropSeason, ResultStatus
from tests.conftest import FarmSetup, auth_header

WET_2026 = {"season": "wet", "season_year": 2026}


@pytest.fixture
def categories(client: TestClient, member_token: str) -> dict[str, int]:
    rows = client.get("/api/v1/expense-categories", headers=auth_header(member_token)).json()
    return {row["category_name"]: row["category_id"] for row in rows}


def expense(client, token, farm: FarmSetup, category_id, amount, field=None, **season):
    body = {
        "category_id": category_id,
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


def harvest(client, token, cycle_id, kg, price, final=False):
    body = {
        "harvest_date": "2026-09-15",
        "quantity_kg": kg,
        "unit_price_php": price,
        "final_harvest": final,
    }
    response = client.post(
        f"/api/v1/cycles/{cycle_id}/harvests", json=body, headers=auth_header(token)
    )
    assert response.status_code == 201, response.json()


def scan(db, cycle_id, result, disease=None, when=None, user_id=None, crop_id=None):
    """A recorded scan; disease is a Disease row for a 'diseased' result."""
    if crop_id is None:
        crop_id = db.scalar(
            select(CropVariety.crop_id)
            .join(CropCycle, CropCycle.variety_id == CropVariety.variety_id)
            .where(CropCycle.cycle_id == cycle_id)
        )
    db.add(
        Diagnosis(
            user_id=user_id or db.scalar(select(User.user_id).order_by(User.user_id)),
            crop_id=crop_id,
            cycle_id=cycle_id,
            disease_id=disease.disease_id if disease else None,
            image_path="leaf/2026/09/test.jpg",
            predicted_label=disease.model_class_label if disease else "corn_healthy",
            confidence=0.9,
            result_status=result,
            model_version="test-1",
            **({"created_at": when} if when else {}),
        )
    )
    db.commit()


def disease(db, crop_name, name, label):
    crop_id = db.scalar(select(Crop.crop_id).where(Crop.crop_name == crop_name))
    row = Disease(crop_id=crop_id, disease_name=name, model_class_label=label, pathogen_type="pest")
    db.add(row)
    db.commit()
    return row


def report(client, token, farm_id, **params):
    return client.get(f"/api/v1/farms/{farm_id}/report", params=params, headers=auth_header(token))


def test_report_per_field_and_totals_match_the_summary(
    client: TestClient, member_token: str, worker_token: str, wet_2026: FarmSetup, categories
):
    farm = wet_2026
    expense(client, member_token, farm, categories["Seeds"], 9800, field="Field A")
    expense(client, worker_token, farm, categories["Fertilizer"], 7000.50, field="Field B")
    expense(client, member_token, farm, categories["Others"], 600)  # whole farm
    expense(client, member_token, farm, categories["Labor"], 999, season="dry", season_year=2026)
    harvest(client, member_token, farm.cycle_ids["Field A"], 5000, 17)

    response = report(client, member_token, farm.farm_id, **WET_2026)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["farm_name"], body["season"], body["season_year"]) == ("MPMPC Farm", "wet", 2026)
    field_a, field_b = body["fields"]
    assert field_a == {
        "field_name": "Field A",
        "crop_name": "Corn",
        "variety_name": "NK6410",
        "area_ha": 1.25,
        "planting_date": "2026-06-15",
        "status": "active",
        "expenses_php": 9800.0,
        "harvest_kg": 5000.0,
        "gross_income_php": 85000.0,
        "net_profit_php": 75200.0,
        "actual_yield_t_ha": 4.0,
        "task_completion_pct": 0,
        "scans": {"diseased": 0, "healthy": 0, "unrecognized": 0},
        "top_disease": None,
    }
    # No harvest yet: the yield is null, not zero.
    assert field_b["field_name"] == "Field B"
    assert (field_b["harvest_kg"], field_b["actual_yield_t_ha"]) == (0.0, None)
    assert field_b["net_profit_php"] == -7000.5

    summary = client.get(
        f"/api/v1/farms/{farm.farm_id}/summary",
        params=WET_2026,
        headers=auth_header(member_token),
    ).json()
    totals = body["totals"]
    assert totals == {
        "area_ha": 2.5,
        "expenses_php": 17400.5,
        "whole_farm_expenses_php": 600.0,
        "harvest_kg": 5000.0,
        "gross_income_php": 85000.0,
        "net_profit_php": 67599.5,
    }
    assert totals["expenses_php"] == summary["total_expenses_php"]
    assert totals["whole_farm_expenses_php"] == summary["whole_farm_expenses_php"]
    assert totals["gross_income_php"] == summary["gross_income_php"]
    assert totals["net_profit_php"] == summary["net_profit_php"]
    # The whole-farm expense counts in the totals but not on any field.
    assert sum(f["expenses_php"] for f in body["fields"]) + 600 == totals["expenses_php"]


def test_without_season_the_current_one_is_used(
    client: TestClient, member_token: str, wet_2026: FarmSetup
):
    body = report(client, member_token, wet_2026.farm_id).json()
    assert (body["season"], body["season_year"]) == ("wet", 2026)
    assert len(body["fields"]) == 2


def test_another_season_has_no_fields(
    client: TestClient, member_token: str, wet_2026: FarmSetup, categories
):
    expense(
        client, member_token, wet_2026, categories["Labor"], 999, season="dry", season_year=2026
    )

    body = report(client, member_token, wet_2026.farm_id, season="dry", season_year=2026).json()

    assert body["fields"] == []
    assert body["totals"]["expenses_php"] == 999.0
    assert body["totals"]["area_ha"] == 0


def test_a_cycle_belongs_to_its_recorded_season(
    client: TestClient, db, member_token: str, wet_2026: FarmSetup
):
    """The recorded season decides, as in /summary: a June sowing recorded as dry is dry 2026."""
    cycle = db.get(CropCycle, wet_2026.cycle_ids["Field B"])
    cycle.season = CropSeason.DRY
    db.commit()

    wet = report(client, member_token, wet_2026.farm_id, **WET_2026).json()
    dry = report(client, member_token, wet_2026.farm_id, season="dry", season_year=2026).json()

    assert [f["field_name"] for f in wet["fields"]] == ["Field A"]
    assert [f["field_name"] for f in dry["fields"]] == ["Field B"]


def test_harvested_cycle_and_yield_rounding(
    client: TestClient, member_token: str, wet_2026: FarmSetup
):
    harvest(client, member_token, wet_2026.cycle_ids["Field B"], 3333, 20, final=True)

    field_b = report(client, member_token, wet_2026.farm_id, **WET_2026).json()["fields"][1]

    assert field_b["status"] == "harvested"
    assert field_b["actual_yield_t_ha"] == 2.67  # 3.333 t / 1.25 ha, rounded half up


def test_scans_top_disease_and_task_completion(
    client: TestClient, db, member_token: str, wet_2026: FarmSetup
):
    cycle_a = wet_2026.cycle_ids["Field A"]
    borer = disease(db, "Corn", "Corn borer", "corn_borer")
    armyworm = disease(db, "Corn", "Armyworm", "corn_armyworm")
    for found in (borer, borer, armyworm, armyworm):
        scan(db, cycle_a, ResultStatus.DISEASED, found)
    scan(db, cycle_a, ResultStatus.HEALTHY)
    scan(db, cycle_a, ResultStatus.UNRECOGNIZED)
    scan(db, None, ResultStatus.HEALTHY, crop_id=borer.crop_id)  # no field: not on the report
    for title in ("Check the field", "Buy seeds", "Fix the fence"):
        body = {"title": title, "scheduled_date": "2026-07-01", "client_uuid": str(uuid.uuid4())}
        created = client.post(
            f"/api/v1/cycles/{cycle_a}/activities", json=body, headers=auth_header(member_token)
        )
        assert created.status_code == 201, created.json()
    tasks = db.scalars(select(CropActivity).where(CropActivity.cycle_id == cycle_a)).all()
    tasks[0].status = ActivityStatus.DONE
    tasks[1].status = ActivityStatus.SKIPPED
    db.commit()

    field_a = report(client, member_token, wet_2026.farm_id, **WET_2026).json()["fields"][0]

    assert field_a["scans"] == {"diseased": 4, "healthy": 1, "unrecognized": 1}
    assert field_a["top_disease"] == "Armyworm"  # a tie goes to the name A to Z
    assert field_a["task_completion_pct"] == 67  # done and skipped of 3, rounded


@pytest.mark.parametrize(
    ("token_name", "code"),
    [("worker_token", "not_farm_owner"), ("outsider_token", "not_farm_member")],
)
def test_only_the_owner_sees_the_report(
    request, client: TestClient, wet_2026: FarmSetup, token_name, code
):
    token = request.getfixturevalue(token_name)
    response = report(client, token, wet_2026.farm_id)
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": code}}


def test_admin_and_unknown_farm(client: TestClient, admin_token: str, member_token: str, farm):
    assert report(client, admin_token, farm.farm_id).json() == {
        "detail": {"code": "not_farm_member"}
    }
    assert report(client, member_token, 999999).json() == {"detail": {"code": "not_farm_member"}}
    assert client.get(f"/api/v1/farms/{farm.farm_id}/report").status_code == 401


def test_season_incomplete(client: TestClient, member_token: str, farm: FarmSetup):
    response = report(client, member_token, farm.farm_id, season="wet")
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "season_incomplete"}}
