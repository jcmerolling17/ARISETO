"""POST /cycles/{cycle_id}/harvests and GET /farms/{farm_id}/harvests."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.seasons import philippine_today
from app.models import CropCycle, HarvestRecord
from app.models.enums import CropSeason, CycleStatus
from app.services import harvest_service
from tests.conftest import FarmSetup, auth_header


def _url(cycle_id: int) -> str:
    return f"/api/v1/cycles/{cycle_id}/harvests"


def _body(**overrides) -> dict:
    body = {
        "harvest_date": philippine_today().isoformat(),
        "quantity_kg": 5100,
        "unit_price_php": 18.5,
        "final_harvest": False,
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not ...}


def _post(client: TestClient, token: str, cycle_id: int, body: dict):
    return client.post(_url(cycle_id), json=body, headers=auth_header(token))


def _cycle(db, cycle_id: int) -> CropCycle:
    db.expire_all()
    return db.get(CropCycle, cycle_id)


def _count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(HarvestRecord))


# ---------- POST ----------


def test_owner_records_a_harvest_and_the_cycle_stays_open(
    client: TestClient, db, member_token: str, farm: FarmSetup
):
    cycle_id = farm.cycle_ids["Field A"]

    response = _post(client, member_token, cycle_id, _body())

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "harvest_id": body["harvest_id"],
        "gross_income_php": 94350.0,
        "cycle_status": "active",
    }
    assert db.get(HarvestRecord, body["harvest_id"]).gross_income_php == 94350
    assert _cycle(db, cycle_id).actual_harvest_date is None


def test_final_harvest_closes_the_cycle_in_the_same_request(
    client: TestClient, db, member_token: str, farm: FarmSetup
):
    cycle_id = farm.cycle_ids["Field A"]
    day = philippine_today() - timedelta(days=2)

    response = _post(
        client, member_token, cycle_id, _body(harvest_date=day.isoformat(), final_harvest=True)
    )

    assert response.status_code == 201
    assert response.json()["cycle_status"] == "harvested"
    cycle = _cycle(db, cycle_id)
    assert cycle.status == CycleStatus.HARVESTED
    assert cycle.actual_harvest_date == day


def test_several_harvests_then_a_final_one(
    client: TestClient, db, member_token: str, farm: FarmSetup
):
    cycle_id = farm.cycle_ids["Field B"]
    for _ in range(2):
        assert _post(client, member_token, cycle_id, _body()).status_code == 201

    final = _post(client, member_token, cycle_id, _body(final_harvest=True))

    assert final.json()["cycle_status"] == "harvested"
    assert _count(db) == 3


@pytest.mark.parametrize("status", [CycleStatus.HARVESTED, CycleStatus.FAILED])
def test_closed_cycle_is_cycle_closed(
    client: TestClient, db, member_token: str, farm: FarmSetup, status: CycleStatus
):
    cycle_id = farm.cycle_ids["Field A"]
    db.get(CropCycle, cycle_id).status = status
    db.commit()

    response = _post(client, member_token, cycle_id, _body())

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cycle_closed"}}
    assert _count(db) == 0


def test_a_harvest_after_the_final_one_is_cycle_closed(
    client: TestClient, member_token: str, farm: FarmSetup
):
    cycle_id = farm.cycle_ids["Field A"]
    _post(client, member_token, cycle_id, _body(final_harvest=True))

    response = _post(client, member_token, cycle_id, _body())

    assert response.json() == {"detail": {"code": "cycle_closed"}}


def test_a_worker_is_not_farm_owner(client: TestClient, db, worker_token: str, farm: FarmSetup):
    response = _post(client, worker_token, farm.cycle_ids["Field A"], _body())

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_owner"}}
    assert _count(db) == 0


def test_non_member_or_missing_cycle_is_cycle_not_found(
    client: TestClient, outsider_token: str, member_token: str, farm: FarmSetup
):
    for token, cycle_id in ((outsider_token, farm.cycle_ids["Field A"]), (member_token, 999999)):
        response = _post(client, token, cycle_id, _body())
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "cycle_not_found"}}


def test_checks_run_not_found_then_owner_then_closed_then_date(
    client: TestClient, db, worker_token: str, farm: FarmSetup
):
    """A worker on a closed cycle with a bad date still gets not_farm_owner."""
    cycle_id = farm.cycle_ids["Field A"]
    db.get(CropCycle, cycle_id).status = CycleStatus.HARVESTED
    db.commit()

    response = _post(client, worker_token, cycle_id, _body(harvest_date="2000-01-01"))

    assert response.json() == {"detail": {"code": "not_farm_owner"}}


def test_harvest_date_must_be_between_sowing_and_philippine_today(
    client: TestClient, db, member_token: str, farm: FarmSetup, monkeypatch
):
    cycle_id = farm.cycle_ids["Field A"]
    cycle = db.get(CropCycle, cycle_id)
    cycle.planting_date = date(2026, 7, 1)
    db.commit()
    monkeypatch.setattr(harvest_service, "philippine_today", lambda: date(2026, 10, 1))

    for day in ("2026-06-30", "2026-10-02"):
        response = _post(client, member_token, cycle_id, _body(harvest_date=day))
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "harvest_date_out_of_range"}}
    for day in ("2026-07-01", "2026-10-01"):
        assert _post(client, member_token, cycle_id, _body(harvest_date=day)).status_code == 201


def test_a_cycle_sown_in_the_future_cannot_be_harvested_yet(
    client: TestClient, db, member_token: str, farm: FarmSetup
):
    cycle_id = farm.cycle_ids["Field A"]
    cycle = db.get(CropCycle, cycle_id)
    cycle.planting_date, cycle.status = philippine_today() + timedelta(days=5), CycleStatus.PLANNED
    db.commit()

    response = _post(client, member_token, cycle_id, _body())

    assert response.json() == {"detail": {"code": "harvest_date_out_of_range"}}


@pytest.mark.parametrize(
    "overrides",
    [
        {"final_harvest": ...},
        {"final_harvest": "true"},
        {"final_harvest": None},
        {"quantity_kg": 0},
        {"unit_price_php": -1},
        {"unit_price_php": 18.555},
        {"quantity_kg": 99999999.99, "unit_price_php": 99999999.99},
        {"harvest_date": ...},
        {"cycle_status": "harvested"},
    ],
)
def test_invalid_body_uses_fastapi_422(
    client: TestClient, db, member_token: str, farm: FarmSetup, overrides: dict
):
    response = _post(client, member_token, farm.cycle_ids["Field A"], _body(**overrides))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert _count(db) == 0


# ---------- GET /farms/{farm_id}/harvests ----------


def _list(client: TestClient, token: str, farm_id: int, **params):
    return client.get(
        f"/api/v1/farms/{farm_id}/harvests", params=params, headers=auth_header(token)
    )


def _sow(db, cycle_id: int, season: CropSeason, sown: date) -> None:
    cycle = db.get(CropCycle, cycle_id)
    cycle.season, cycle.planting_date = season, sown
    db.commit()


def test_list_is_the_seasons_harvests_newest_first(
    client: TestClient, db, member_token: str, worker_token: str, farm: FarmSetup, monkeypatch
):
    monkeypatch.setattr(harvest_service, "philippine_today", lambda: date(2026, 10, 1))
    _sow(db, farm.cycle_ids["Field A"], CropSeason.WET, date(2026, 6, 15))
    _sow(db, farm.cycle_ids["Field B"], CropSeason.DRY, date(2026, 12, 15))
    older = _post(
        client, member_token, farm.cycle_ids["Field A"], _body(harvest_date="2026-09-01")
    ).json()
    newer = _post(
        client, member_token, farm.cycle_ids["Field A"], _body(harvest_date="2026-09-20")
    ).json()

    rows = _list(client, worker_token, farm.farm_id, season="wet", season_year=2026).json()

    assert [row["harvest_id"] for row in rows] == [newer["harvest_id"], older["harvest_id"]]
    assert rows[0] == {
        "harvest_id": newer["harvest_id"],
        "cycle_id": farm.cycle_ids["Field A"],
        "field_name": "Field A",
        "crop_name": "Corn",
        "harvest_date": "2026-09-20",
        "quantity_kg": 5100.0,
        "unit_price_php": 18.5,
        "gross_income_php": 94350.0,
    }


def test_list_season_follows_the_cycles_season_year(
    client: TestClient, db, member_token: str, farm: FarmSetup, monkeypatch
):
    """A dry cycle sown in January belongs to the dry season that began the December before."""
    monkeypatch.setattr(harvest_service, "philippine_today", lambda: date(2027, 3, 1))
    _sow(db, farm.cycle_ids["Field B"], CropSeason.DRY, date(2027, 1, 5))
    harvest = _post(
        client, member_token, farm.cycle_ids["Field B"], _body(harvest_date="2027-02-20")
    ).json()

    in_2026 = _list(client, member_token, farm.farm_id, season="dry", season_year=2026).json()
    in_2027 = _list(client, member_token, farm.farm_id, season="dry", season_year=2027).json()

    assert [row["harvest_id"] for row in in_2026] == [harvest["harvest_id"]]
    assert in_2027 == []


def test_list_field_filter(client: TestClient, db, member_token: str, farm: FarmSetup, monkeypatch):
    monkeypatch.setattr(harvest_service, "philippine_today", lambda: date(2026, 10, 1))
    for name in ("Field A", "Field B"):
        _sow(db, farm.cycle_ids[name], CropSeason.WET, date(2026, 6, 15))
        _post(client, member_token, farm.cycle_ids[name], _body(harvest_date="2026-09-01"))

    rows = _list(
        client,
        member_token,
        farm.farm_id,
        season="wet",
        season_year=2026,
        field_id=farm.field_ids["Field B"],
    ).json()

    assert [row["field_name"] for row in rows] == ["Field B"]


def test_list_errors(
    client: TestClient,
    member_token: str,
    outsider_token: str,
    farm: FarmSetup,
    other_farm: FarmSetup,
):
    assert _list(client, outsider_token, farm.farm_id).json() == {
        "detail": {"code": "not_farm_member"}
    }
    assert _list(client, member_token, farm.farm_id, season="wet").json() == {
        "detail": {"code": "season_incomplete"}
    }
    assert _list(
        client, member_token, farm.farm_id, field_id=other_farm.field_ids["Field A"]
    ).json() == {"detail": {"code": "field_not_in_farm"}}
