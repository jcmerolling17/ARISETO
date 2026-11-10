"""Calendar templates from the seed file and the tasks generated from them (Section 6,
"Crop calendar (Phase 7)" and "Calendar template schedules (Phase 7)")."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.core.seasons import philippine_today
from app.models import CalendarTemplateTask, CropActivity, CropCycle
from app.services import calendar_service, seed_service
from tests.conftest import auth_header

DAY = timedelta(days=1)


def _template_counts(db) -> dict[str, int]:
    return seed_service.template_counts(db)


# ---------- The seed ----------


def test_seed_copies_each_crops_template_to_every_variety(db, seeded_varieties) -> None:
    # 5 varieties per crop: rice 8 rows, corn 7, onion 14.
    assert _template_counts(db) == {"Corn": 35, "Onion": 70, "Rice": 40}
    per_variety = {
        name: db.scalar(select(func.count()).where(CalendarTemplateTask.variety_id == variety_id))
        for name, variety_id in seeded_varieties.items()
    }
    assert per_variety["RC-18"] == 8
    assert per_variety["DEKALB 8282"] == 7
    assert per_variety["RED ALLIUM"] == 14
    assert set(per_variety.values()) == {7, 8, 14}


def test_seed_is_safe_to_run_again(db, seeded_varieties) -> None:
    result = seed_service.seed_calendar_templates(db)
    db.commit()
    assert (result.added, result.updated) == (0, 145)
    assert sum(_template_counts(db).values()) == 145


def test_seed_rows_match_the_pdf(db, seeded_varieties) -> None:
    def row(variety: str, name: str) -> CalendarTemplateTask:
        return db.scalar(
            select(CalendarTemplateTask).where(
                CalendarTemplateTask.variety_id == seeded_varieties[variety],
                CalendarTemplateTask.task_name == name,
            )
        )

    irrigate = row("RED DRAGON", "Irrigate")
    assert (irrigate.anchor, irrigate.day_offset, irrigate.repeat_every_days) == ("sowing", 0, 7)
    assert (irrigate.repeat_until_anchor, irrigate.repeat_until_offset) == ("harvest", -5)
    assert irrigate.source_reference == "DA RFO 02 Onion Production Guide (2012), p. 5"

    second = row("RED DRAGON", "2nd fertilizer")
    assert second.description == (
        "Nitrogen with phosphorus (P2O5), band 5 cm from the plant and 8 cm deep"
    )
    assert (second.day_offset, second.day_offset_end, second.is_weather_sensitive) == (20, 30, True)
    assert (second.growth_stage, second.task_type) == ("vegetative", "fertilization")

    land = row("SUPER PINOY", "Before sowing: land preparation")
    assert land.description == (
        'Weedicide on "mutha" if present, 2 plowings and 2 harrowings, raised beds 75 cm '
        "wide and 10 to 15 cm high"
    )
    assert land.source_reference == "DA RFO 02 Onion Production Guide (2012), pp. 3 to 4"

    drain = row("RC-402", "Drain the field")
    assert (drain.anchor, drain.day_offset, drain.day_offset_end) == ("harvest", -14, -7)
    assert drain.source_reference == "PhilRice PalayCheck System 2022"

    sowing = row("NK6410", "Sowing")
    assert (sowing.growth_stage, sowing.task_type) == ("seed_sowing", "planting")
    assert sowing.source_reference == "the field's sowing date"
    assert row("NK6410", "Harvest").source_reference == "DA RFO 02 Corn Technoguide (2012)"


def test_a_bad_seed_row_loads_nothing(db, seeded_varieties, tmp_path: Path) -> None:
    source = seed_service.CALENDAR_CSV.read_text(encoding="utf-8").splitlines()
    source[1] = source[1].replace("seed_sowing", "sprouting")
    bad = tmp_path / "calendar_templates.csv"
    bad.write_text("\n".join(source), encoding="utf-8")

    with pytest.raises(seed_service.SeedFileError, match="line 2: unknown growth_stage"):
        seed_service.seed_calendar_templates(db, bad)


def test_cli_seed_reports_template_counts(db, capsys) -> None:
    assert cli.main(["seed"]) == 0
    out = capsys.readouterr().out
    assert "calendar templates: 145 added, 0 updated" in out
    assert "Calendar template tasks per crop (145 in total):" in out


# ---------- Generation ----------


def _tasks(db, cycle_id: int) -> list[CropActivity]:
    return list(
        db.scalars(
            select(CropActivity)
            .where(CropActivity.cycle_id == cycle_id)
            .order_by(CropActivity.scheduled_date, CropActivity.activity_id)
        )
    )


def _by_title(tasks: list[CropActivity]) -> dict[str, CropActivity]:
    return {task.title: task for task in tasks}


def test_rice_calendar(db, calendar_farm) -> None:
    cycle = db.get(CropCycle, calendar_farm.cycle_ids["Field B"])
    sown, harvest = cycle.planting_date, cycle.expected_harvest_date
    assert harvest == sown + 110 * DAY
    tasks = _tasks(db, cycle.cycle_id)
    assert len(tasks) == 8
    by = _by_title(tasks)
    assert (by["Sowing"].scheduled_date, by["Sowing"].end_date) == (sown, None)
    assert (by["Basal fertilizer"].scheduled_date, by["Basal fertilizer"].end_date) == (
        sown + 7 * DAY,
        sown + 10 * DAY,
    )
    assert by["Weed control"].end_date == sown + 45 * DAY
    assert (by["Drain the field"].scheduled_date, by["Drain the field"].end_date) == (
        harvest - 14 * DAY,
        harvest - 7 * DAY,
    )
    harvest_task = by["Harvest at grain maturity"]
    assert (harvest_task.scheduled_date, harvest_task.is_weather_sensitive) == (harvest, True)
    assert (harvest_task.task_type, harvest_task.growth_stage) == ("harvest", "harvest")
    assert all(task.status == "pending" and task.reminder is False for task in tasks)
    assert all(task.template_task_id is not None for task in tasks)
    assert len({task.client_uuid for task in tasks}) == 8


def test_corn_calendar(db, calendar_farm) -> None:
    cycle = db.get(CropCycle, calendar_farm.cycle_ids["Field A"])
    sown = cycle.planting_date
    tasks = _tasks(db, cycle.cycle_id)
    assert len(tasks) == 7
    by = _by_title(tasks)
    assert by["Trichogramma release, second"].scheduled_date == sown + 35 * DAY
    assert by["Trichogramma release, second"].end_date == sown + 37 * DAY
    assert by["Harvest"].scheduled_date == sown + 90 * DAY
    assert [t.title for t in tasks if t.is_weather_sensitive] == [
        "Hilling-up with the second nitrogen side-dressing",
        "Trichogramma release for corn borer, first",
        "Trichogramma release, second",
        "Harvest",
    ]


def _add_onion(client: TestClient, token: str, farm_id: int, variety_id: int, name: str, sown):
    body = {
        "field_name": name,
        "area_ha": 0.5,
        "variety_id": variety_id,
        "season": "dry",
        "planting_date": sown.isoformat(),
    }
    response = client.post(f"/api/v1/farms/{farm_id}/fields", json=body, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()["cycle_id"]


@pytest.mark.parametrize(
    ("variety", "days", "repeats", "total"),
    [
        ("RED DRAGON", 125, 18, 31),
        ("SUPER TAKII (White Onion)", 105, 15, 28),
        ("SUPER PINOY", 110, 16, 29),
        ("RED PINOY", 120, 17, 30),
    ],
)
def test_onion_calendar_with_add_plot(
    client: TestClient,
    db,
    member_token: str,
    calendar_farm,
    seeded_varieties,
    variety: str,
    days: int,
    repeats: int,
    total: int,
) -> None:
    sown = philippine_today() + 3 * DAY
    cycle_id = _add_onion(
        client, member_token, calendar_farm.farm_id, seeded_varieties[variety], "Onion plot", sown
    )

    tasks = _tasks(db, cycle_id)
    assert len(tasks) == total
    irrigations = [t.scheduled_date for t in tasks if t.title == "Irrigate"]
    assert len(irrigations) == repeats
    assert irrigations[0] == sown
    assert irrigations[-1] <= sown + (days - 5) * DAY < irrigations[-1] + 7 * DAY
    assert all(b - a == 7 * DAY for a, b in zip(irrigations, irrigations[1:], strict=False))
    by = _by_title(tasks)
    # "Before sowing" tasks are placed on the sowing day.
    assert by["Before sowing: land preparation"].scheduled_date == sown
    assert by["Before sowing: basal fertilizer"].is_weather_sensitive is True
    assert by["Stop irrigating"].scheduled_date == sown + (days - 5) * DAY
    assert by["Stop irrigating"].end_date == sown + (days - 3) * DAY
    assert by[
        "Cure the bulbs in a sunny, well-ventilated area for 10 to 14 days"
    ].scheduled_date == (sown + days * DAY)


def test_template_dates_for_a_repeat_ending_on_its_last_day() -> None:
    task = CalendarTemplateTask(
        anchor="sowing",
        day_offset=0,
        day_offset_end=None,
        repeat_every_days=7,
        repeat_until_anchor="sowing",
        repeat_until_offset=14,
    )
    cycle = CropCycle(planting_date=date(2026, 11, 1), expected_harvest_date=date(2027, 2, 1))
    assert calendar_service.template_dates(task, cycle) == [
        (date(2026, 11, 1), None),
        (date(2026, 11, 8), None),
        (date(2026, 11, 15), None),
    ]


def test_a_failed_farm_setup_saves_no_tasks(
    client: TestClient, db, member_token: str, barangay_id: int, seeded_varieties
) -> None:
    body = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "season": "wet",
        "fields": [
            {
                "field_name": "A",
                "area_ha": 1,
                "variety_id": seeded_varieties["NK6410"],
                "planting_date": philippine_today().isoformat(),
            },
            {
                "field_name": "B",
                "area_ha": 1,
                "variety_id": 999999,
                "planting_date": philippine_today().isoformat(),
            },
        ],
    }
    response = client.post("/api/v1/farms", json=body, headers=auth_header(member_token))
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(CropActivity)) == 0


# ---------- generate-calendar ----------


def test_generate_calendar_fills_only_open_cycles_without_tasks(db, calendar_farm, capsys) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    rice = calendar_farm.cycle_ids["Field B"]
    # Rice loses its tasks, as if created before Phase 7; corn keeps its own.
    for task in _tasks(db, rice):
        db.delete(task)
    db.commit()

    assert cli.main(["generate-calendar"]) == 0
    assert "Calendar generated: 8 tasks for 1 cycles; 1 skipped" in capsys.readouterr().out
    assert len(_tasks(db, rice)) == 8
    assert len(_tasks(db, corn)) == 7

    # Running it again never duplicates.
    assert cli.main(["generate-calendar"]) == 0
    assert "0 tasks for 0 cycles; 2 skipped" in capsys.readouterr().out
    assert len(_tasks(db, rice)) == 8


def test_generate_calendar_skips_harvested_and_failed_cycles(db, calendar_farm) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    for task in _tasks(db, rice):
        db.delete(task)
    db.get(CropCycle, rice).status = "harvested"
    db.commit()

    summary = calendar_service.generate_missing(db, rice)
    assert (summary.generated, summary.skipped) == ({}, [rice])
    assert _tasks(db, rice) == []


def test_generate_calendar_for_one_cycle(db, calendar_farm, capsys) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    for task in _tasks(db, rice):
        db.delete(task)
    db.commit()

    assert cli.main(["generate-calendar", "--cycle-id", str(rice)]) == 0
    assert "8 tasks for 1 cycles; 0 skipped" in capsys.readouterr().out


def test_generate_calendar_unknown_cycle(db, capsys) -> None:
    assert cli.main(["generate-calendar", "--cycle-id", "999"]) == 1
    assert "Cycle 999 not found." in capsys.readouterr().err
