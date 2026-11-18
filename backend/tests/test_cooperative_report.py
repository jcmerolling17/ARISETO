"""GET /admin/reports/cooperative (DFD 7.6, Phase 13): farm results rolled up by crop for one
season, built from the same per-farm figures as the farm report; no member names or contact
details. Made-up test data; the San Jose barangay row is copied from barangays.csv."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.models import Barangay, CropCycle, Farm
from app.models.enums import AccountStatus, CropSeason, ResultStatus
from tests.conftest import (
    FarmSetup,
    auth_header,
    create_active_member,
    create_farm,
)
from tests.test_farm_report import WET_2026, disease, harvest, report, scan

REPORT = "/api/v1/admin/reports/cooperative"
AMBULONG = {
    "psgc_code": "1705110001",
    "municipality": "San Jose",
    "barangay_name": "Ambulong",
    "center_latitude": "12.210220",
    "center_longitude": "121.018679",
}
IN_SEASON = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
AFTER_SEASON = datetime(2026, 12, 5, 4, 0, tzinfo=UTC)


@pytest.fixture
def san_jose_farm(client, db, outsider_token, variety_ids, wet_2026) -> FarmSetup:
    """The outsider's farm in San Jose, both fields sown June 15, 2026 (wet 2026)."""
    barangay = Barangay(**AMBULONG)
    db.add(barangay)
    db.commit()
    return create_farm(client, outsider_token, barangay.barangay_id, variety_ids, date(2026, 6, 15))


def _cooperative(client, token, **params):
    return client.get(REPORT, params=params, headers=auth_header(token))


def test_sums_by_crop_scans_and_diseases(
    client: TestClient,
    db,
    admin_token: str,
    member_token: str,
    outsider_token: str,
    wet_2026: FarmSetup,
    san_jose_farm: FarmSetup,
):
    harvest(client, member_token, wet_2026.cycle_ids["Field A"], 5000, 17)
    harvest(client, outsider_token, san_jose_farm.cycle_ids["Field A"], 2500, 17)
    harvest(client, outsider_token, san_jose_farm.cycle_ids["Field B"], 4000, 20, final=True)
    borer = disease(db, "Corn", "Corn borer", "corn_borer")
    blast = disease(db, "Rice", "Rice blast", "rice_blast")
    scan(db, wet_2026.cycle_ids["Field A"], ResultStatus.DISEASED, borer, IN_SEASON)
    scan(db, san_jose_farm.cycle_ids["Field B"], ResultStatus.DISEASED, blast, IN_SEASON)
    scan(db, san_jose_farm.cycle_ids["Field A"], ResultStatus.DISEASED, borer, IN_SEASON)
    scan(db, wet_2026.cycle_ids["Field B"], ResultStatus.HEALTHY, None, IN_SEASON)
    scan(db, wet_2026.cycle_ids["Field B"], ResultStatus.UNRECOGNIZED, None, AFTER_SEASON)

    response = _cooperative(client, admin_token, **WET_2026)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["season"], body["season_year"]) == ("wet", 2026)
    assert body["active_members"] == 2  # the owner and the outsider; the admin is not counted
    assert body["farms"] == 2
    assert body["by_crop"] == [
        {
            "crop_name": "Rice",
            "cycles": 2,
            "area_ha": 2.5,
            "harvested_cycles": 1,
            "harvest_kg": 4000.0,
            "avg_yield_t_ha": 3.2,  # 4 t over the 1.25 ha that has a harvest
        },
        {
            "crop_name": "Corn",
            "cycles": 2,
            "area_ha": 2.5,
            "harvested_cycles": 0,
            "harvest_kg": 7500.0,
            "avg_yield_t_ha": 3.0,
        },
    ]
    assert body["diseases"] == [
        {"crop_name": "Corn", "disease_name": "Corn borer", "scans": 2},
        {"crop_name": "Rice", "disease_name": "Rice blast", "scans": 1},
    ]
    # The December scan belongs to dry 2026.
    assert body["scans"] == {"diseased": 3, "healthy": 1, "unrecognized": 0}


def test_crops_are_listed_in_crop_order(
    client: TestClient, db, admin_token: str, wet_2026: FarmSetup
):
    from sqlalchemy import select

    from app.models import Crop

    crop_order = [c.crop_name for c in db.scalars(select(Crop).order_by(Crop.crop_id))]
    names = [
        c["crop_name"] for c in _cooperative(client, admin_token, **WET_2026).json()["by_crop"]
    ]

    assert names == [name for name in crop_order if name in names]
    assert sorted(names) == ["Corn", "Rice"]


def test_matches_the_farm_reports(
    client: TestClient,
    admin_token: str,
    member_token: str,
    outsider_token: str,
    wet_2026: FarmSetup,
    san_jose_farm: FarmSetup,
):
    harvest(client, member_token, wet_2026.cycle_ids["Field A"], 5000, 17)
    harvest(client, outsider_token, san_jose_farm.cycle_ids["Field B"], 4000, 20)

    farms = [
        report(client, member_token, wet_2026.farm_id, **WET_2026).json(),
        report(client, outsider_token, san_jose_farm.farm_id, **WET_2026).json(),
    ]
    body = _cooperative(client, admin_token, **WET_2026).json()

    assert sum(c["harvest_kg"] for c in body["by_crop"]) == sum(
        f["totals"]["harvest_kg"] for f in farms
    )
    assert sum(c["area_ha"] for c in body["by_crop"]) == sum(f["totals"]["area_ha"] for f in farms)
    assert sum(c["cycles"] for c in body["by_crop"]) == sum(len(f["fields"]) for f in farms)


def test_municipality_filter(
    client: TestClient,
    db,
    admin_token: str,
    wet_2026: FarmSetup,
    san_jose_farm: FarmSetup,
):
    user = create_active_member(
        db,
        mobile_no="+639173333333",
        email="sj@example.com",
        member_no="MPMPC-0045",
        municipality="San Jose",
    )
    pending = create_active_member(
        db,
        mobile_no="+639174444444",
        email="pending@example.com",
        member_no="MPMPC-0046",
        municipality="San Jose",
    )
    pending.account_status = AccountStatus.PENDING
    db.commit()
    borer = disease(db, "Corn", "Corn borer", "corn_borer")
    # No field chosen: placed by the scanning member's municipality.
    scan(db, None, ResultStatus.DISEASED, borer, IN_SEASON, user.user_id, borer.crop_id)
    scan(db, wet_2026.cycle_ids["Field A"], ResultStatus.HEALTHY, None, IN_SEASON)
    scan(db, san_jose_farm.cycle_ids["Field A"], ResultStatus.HEALTHY, None, IN_SEASON)

    san_jose = _cooperative(client, admin_token, **WET_2026, municipality="San Jose").json()
    mamburao = _cooperative(client, admin_token, **WET_2026, municipality="Mamburao").json()
    everything = _cooperative(client, admin_token, **WET_2026).json()

    # Members are placed by their own municipality; the two farm members live in Sablayan.
    assert san_jose["active_members"] == 1
    assert mamburao["active_members"] == 0
    assert everything["active_members"] == 3
    assert (san_jose["farms"], mamburao["farms"], everything["farms"]) == (1, 1, 2)
    assert san_jose["scans"] == {"diseased": 1, "healthy": 1, "unrecognized": 0}
    assert mamburao["scans"] == {"diseased": 0, "healthy": 1, "unrecognized": 0}
    assert everything["scans"]["healthy"] == 2
    assert [c["cycles"] for c in san_jose["by_crop"]] == [1, 1]


def test_farms_without_a_cycle_in_the_season_are_not_counted(
    client: TestClient, db, admin_token: str, wet_2026: FarmSetup, san_jose_farm: FarmSetup
):
    for cycle_id in san_jose_farm.cycle_ids.values():
        db.get(CropCycle, cycle_id).season = CropSeason.DRY
    db.commit()

    wet = _cooperative(client, admin_token, **WET_2026).json()
    dry = _cooperative(client, admin_token, season="dry", season_year=2026).json()

    assert (wet["farms"], dry["farms"]) == (1, 1)


def test_no_names_or_contact_details(
    client: TestClient, db, admin_token: str, wet_2026: FarmSetup, san_jose_farm: FarmSetup
):
    text = _cooperative(client, admin_token, **WET_2026).text
    farm_names = [farm.farm_name for farm in db.query(Farm).all()]

    for private in ["Ma. Cristina", "Dela Cruz", "+63917", "@example.com", "MPMPC-00", *farm_names]:
        assert private not in text
    assert set(_cooperative(client, admin_token, **WET_2026).json()) == {
        "season",
        "season_year",
        "active_members",
        "farms",
        "by_crop",
        "diseases",
        "scans",
    }


def test_default_season_and_errors(client: TestClient, admin_token: str, wet_2026: FarmSetup):
    body = _cooperative(client, admin_token).json()
    assert (body["season"], body["season_year"]) == ("wet", 2026)

    incomplete = _cooperative(client, admin_token, season_year=2026)
    assert incomplete.status_code == 422
    assert incomplete.json() == {"detail": {"code": "season_incomplete"}}

    unknown = _cooperative(client, admin_token, municipality="Manila")
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": {"code": "unknown_municipality"}}


def test_empty_season(client: TestClient, admin_token: str):
    body = _cooperative(client, admin_token, season="dry", season_year=2020).json()
    assert body["farms"] == 0
    assert body["by_crop"] == [] and body["diseases"] == []
    assert body["scans"] == {"diseased": 0, "healthy": 0, "unrecognized": 0}
