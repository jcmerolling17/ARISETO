"""The activity endpoints (Section 6): listing a cycle's or a farm's tasks, adding custom
tasks, marking, rescheduling and editing, and deleting custom tasks."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.seasons import philippine_today
from app.models import (
    AlertRule,
    CropActivity,
    CropCycle,
    Notification,
    User,
    WeatherAlert,
    WeatherLog,
)
from tests.conftest import (
    MEMBER_PASSWORD,
    WORKER_MOBILE,
    auth_header,
    create_active_member,
    create_farm,
    login_token,
)

DAY = timedelta(days=1)


def _cycle_url(cycle_id: int) -> str:
    return f"/api/v1/cycles/{cycle_id}/activities"


def _task_url(activity_id: int) -> str:
    return f"/api/v1/activities/{activity_id}"


def _tasks(db, cycle_id: int) -> list[CropActivity]:
    return list(
        db.scalars(
            select(CropActivity)
            .where(CropActivity.cycle_id == cycle_id)
            .order_by(CropActivity.scheduled_date, CropActivity.activity_id)
        )
    )


def _task(db, cycle_id: int, title: str) -> CropActivity:
    return next(task for task in _tasks(db, cycle_id) if task.title == title)


def _custom(client: TestClient, token: str, cycle_id: int, **overrides):
    body = {
        "title": "Check field water level",
        "scheduled_date": philippine_today().isoformat(),
        "client_uuid": str(uuid.uuid4()),
    }
    body.update(overrides)
    return client.post(_cycle_url(cycle_id), json=body, headers=auth_header(token))


@pytest.fixture
def worker(client: TestClient, db, calendar_farm) -> str:
    """An active member who works on the calendar farm (role 'worker')."""
    from app.models import FarmAssignment

    worker = create_active_member(
        db,
        first_name="Pedro",
        last_name="Reyes",
        mobile_no=WORKER_MOBILE,
        email="worker@example.com",
        member_no="MPMPC-0043",
    )
    db.add(
        FarmAssignment(farm_id=calendar_farm.farm_id, user_id=worker.user_id, role_on_farm="worker")
    )
    db.commit()
    return login_token(client, WORKER_MOBILE, MEMBER_PASSWORD)


@pytest.fixture
def other_farm(client: TestClient, outsider_token: str, barangay_id: int, seeded_varieties):
    """A calendar farm owned by the outsider."""
    return create_farm(client, outsider_token, barangay_id, seeded_varieties, philippine_today())


# ---------- GET /cycles/{cycle_id}/activities ----------


def test_lists_a_cycles_tasks_with_its_details(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    response = client.get(_cycle_url(rice), headers=auth_header(member_token))

    assert response.status_code == 200
    body = response.json()
    cycle = db.get(CropCycle, rice)
    assert body["cycle"] == {
        "cycle_id": rice,
        "field_name": "Field B",
        "crop_name": "Rice",
        "variety_name": "RC-402",
        "season": "wet",
        "planting_date": cycle.planting_date.isoformat(),
        "expected_harvest_date": cycle.expected_harvest_date.isoformat(),
        "status": "active",
        "completion_pct": 0,
    }
    assert len(body["items"]) == 8
    basal = next(item for item in body["items"] if item["title"] == "Basal fertilizer")
    assert basal == {
        "activity_id": basal["activity_id"],
        "title": "Basal fertilizer",
        "description": None,
        "source_reference": "PhilRice PalayCheck System 2022",
        "task_type": "fertilization",
        "growth_stage": "vegetative",
        "scheduled_date": (cycle.planting_date + 7 * DAY).isoformat(),
        "end_date": (cycle.planting_date + 10 * DAY).isoformat(),
        "scheduled_time": None,
        "reminder": False,
        "notes": None,
        "status": "pending",
        "completed_at": None,
        "is_weather_sensitive": True,
        "is_custom": False,
    }


def test_order_is_date_then_time_with_untimed_last(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    sown = db.get(CropCycle, corn).planting_date.isoformat()
    late = _custom(
        client, member_token, corn, title="Late", scheduled_date=sown, scheduled_time="15:00"
    ).json()
    early = _custom(
        client, member_token, corn, title="Early", scheduled_date=sown, scheduled_time="06:30"
    ).json()

    items = client.get(_cycle_url(corn), headers=auth_header(member_token)).json()["items"]
    on_sowing_day = [item["title"] for item in items if item["scheduled_date"] == sown]
    assert on_sowing_day[:2] == [early["title"], late["title"]]
    assert set(on_sowing_day[2:]) == {"Sowing", "Keep the field weed-free"}


def test_completion_counts_done_and_skipped(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    tasks = _tasks(db, rice)
    client.patch(
        _task_url(tasks[0].activity_id), json={"status": "done"}, headers=auth_header(member_token)
    )
    client.patch(
        _task_url(tasks[1].activity_id),
        json={"status": "skipped"},
        headers=auth_header(member_token),
    )
    client.patch(
        _task_url(tasks[2].activity_id), json={"status": "done"}, headers=auth_header(member_token)
    )

    body = client.get(_cycle_url(rice), headers=auth_header(member_token)).json()
    assert body["cycle"]["completion_pct"] == 38  # 3 of 8 = 37.5, rounded half up


def test_status_and_date_filters(client: TestClient, db, member_token: str, calendar_farm) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    cycle = db.get(CropCycle, rice)
    first = _tasks(db, rice)[0]
    client.patch(
        _task_url(first.activity_id), json={"status": "done"}, headers=auth_header(member_token)
    )

    done = client.get(
        _cycle_url(rice), params={"status": "done"}, headers=auth_header(member_token)
    ).json()
    assert [item["activity_id"] for item in done["items"]] == [first.activity_id]
    assert done["cycle"]["completion_pct"] == 13  # counts every task, whatever the filters

    # Basal fertilizer runs day 7 to 10, so day 9 alone still finds it.
    day9 = (cycle.planting_date + 9 * DAY).isoformat()
    ranged = client.get(
        _cycle_url(rice), params={"from": day9, "to": day9}, headers=auth_header(member_token)
    ).json()
    assert "Basal fertilizer" in [item["title"] for item in ranged["items"]]
    assert "Harvest at grain maturity" not in [item["title"] for item in ranged["items"]]


def test_any_member_can_list(client: TestClient, worker: str, calendar_farm) -> None:
    response = client.get(
        _cycle_url(calendar_farm.cycle_ids["Field A"]), headers=auth_header(worker)
    )
    assert response.status_code == 200


@pytest.mark.parametrize("cycle", ["other", "unknown"])
def test_non_members_get_cycle_not_found(
    client: TestClient, outsider_token: str, calendar_farm, cycle: str
) -> None:
    cycle_id = calendar_farm.cycle_ids["Field A"] if cycle == "other" else 999999
    response = client.get(_cycle_url(cycle_id), headers=auth_header(outsider_token))
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "cycle_not_found"}}


# ---------- GET /farms/{farm_id}/activities ----------


def test_farm_tasks_cover_each_fields_current_cycle(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    url = f"/api/v1/farms/{calendar_farm.farm_id}/activities"
    items = client.get(url, headers=auth_header(member_token)).json()["items"]

    assert len(items) == 15
    assert {item["field_name"] for item in items} == {"Field A", "Field B"}
    first = items[0]
    assert first["cycle_id"] in calendar_farm.cycle_ids.values()
    assert items == sorted(items, key=lambda i: (i["scheduled_date"], i["scheduled_time"] or "~"))

    field_b = client.get(
        url,
        params={"field_id": calendar_farm.field_ids["Field B"]},
        headers=auth_header(member_token),
    ).json()["items"]
    assert {item["field_name"] for item in field_b} == {"Field B"}

    found = client.get(url, params={"q": "trichogramma"}, headers=auth_header(member_token)).json()[
        "items"
    ]
    assert [item["title"] for item in found] == [
        "Trichogramma release for corn borer, first",
        "Trichogramma release, second",
    ]

    page = client.get(
        url, params={"limit": 2, "offset": 1}, headers=auth_header(member_token)
    ).json()["items"]
    assert page == items[1:3]


def test_a_search_with_wildcards_is_literal(
    client: TestClient, member_token: str, calendar_farm
) -> None:
    url = f"/api/v1/farms/{calendar_farm.farm_id}/activities"
    items = client.get(url, params={"q": "%"}, headers=auth_header(member_token)).json()["items"]
    assert items == []


def test_harvested_cycles_are_left_out(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    db.get(CropCycle, calendar_farm.cycle_ids["Field B"]).status = "harvested"
    db.commit()
    url = f"/api/v1/farms/{calendar_farm.farm_id}/activities"
    items = client.get(url, headers=auth_header(member_token)).json()["items"]
    assert {item["field_name"] for item in items} == {"Field A"}


def test_farm_tasks_errors(
    client: TestClient, member_token: str, outsider_token: str, calendar_farm, other_farm
) -> None:
    url = f"/api/v1/farms/{calendar_farm.farm_id}/activities"
    response = client.get(url, headers=auth_header(outsider_token))
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "not_farm_member"}}

    response = client.get("/api/v1/farms/999999/activities", headers=auth_header(member_token))
    assert response.json() == {"detail": {"code": "not_farm_member"}}

    response = client.get(
        url, params={"field_id": other_farm.field_ids["Field A"]}, headers=auth_header(member_token)
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "field_not_in_farm"}}

    assert (
        client.get(url, params={"limit": 201}, headers=auth_header(member_token)).status_code == 422
    )


# ---------- POST /cycles/{cycle_id}/activities ----------


def test_adds_a_custom_task(client: TestClient, db, worker: str, calendar_farm) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    response = _custom(
        client,
        worker,
        corn,
        title="  Scout   for corn borers ",
        scheduled_time="15:00",
        reminder=True,
        notes="Near the  creek",
        growth_stage="vegetative",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Scout for corn borers"
    assert body["notes"] == "Near the creek"
    assert (body["task_type"], body["is_custom"], body["is_weather_sensitive"]) == (
        "other",
        True,
        False,
    )
    assert (body["scheduled_time"], body["reminder"], body["status"]) == (
        "15:00:00",
        True,
        "pending",
    )
    assert (body["description"], body["source_reference"]) == (None, None)


def test_resending_a_client_uuid_returns_the_saved_task(
    client: TestClient,
    db,
    member_token: str,
    worker: str,
    calendar_farm,
    other_farm,
    outsider_token: str,
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    client_uuid = str(uuid.uuid4())
    first = _custom(client, member_token, corn, client_uuid=client_uuid)
    again = _custom(client, member_token, corn, client_uuid=client_uuid, title="Changed")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert len([t for t in _tasks(db, corn) if t.template_task_id is None]) == 1

    elsewhere = _custom(
        client, outsider_token, other_farm.cycle_ids["Field A"], client_uuid=client_uuid
    )
    assert elsewhere.status_code == 409
    assert elsewhere.json() == {"detail": {"code": "client_uuid_taken"}}


def test_custom_task_errors(
    client: TestClient, db, member_token: str, outsider_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    assert _custom(client, outsider_token, corn).json() == {"detail": {"code": "cycle_not_found"}}

    far = philippine_today().replace(year=philippine_today().year + 3).isoformat()
    response = _custom(client, member_token, corn, scheduled_date=far)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "date_out_of_range"}}

    db.get(CropCycle, corn).status = "failed"
    db.commit()
    response = _custom(client, member_token, corn)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cycle_closed"}}


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},
        {"title": "x" * 101},
        {"notes": "x" * 501},
        {"reminder": "yes"},
        {"growth_stage": "flowering"},
        {"client_uuid": "not-a-uuid"},
        {"task_type": "fertilization"},
    ],
)
def test_custom_task_bad_bodies_get_fastapi_422(
    client: TestClient, member_token: str, calendar_farm, body: dict
) -> None:
    response = _custom(client, member_token, calendar_farm.cycle_ids["Field A"], **body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# ---------- PATCH /activities/{activity_id} ----------


def _patch(client: TestClient, token: str, activity_id: int, body: dict):
    return client.patch(_task_url(activity_id), json=body, headers=auth_header(token))


def test_done_sets_completed_at_and_leaving_done_clears_it(
    client: TestClient, db, worker: str, calendar_farm
) -> None:
    task = _tasks(db, calendar_farm.cycle_ids["Field A"])[0]
    done = _patch(client, worker, task.activity_id, {"status": "done"}).json()
    assert done["status"] == "done" and done["completed_at"] is not None

    again = _patch(client, worker, task.activity_id, {"status": "done"}).json()
    assert again["completed_at"] == done["completed_at"]  # unchanged value, not a change

    back = _patch(client, worker, task.activity_id, {"status": "pending"}).json()
    assert (back["status"], back["completed_at"]) == ("pending", None)
    skipped = _patch(client, worker, task.activity_id, {"status": "skipped"}).json()
    assert (skipped["status"], skipped["completed_at"]) == ("skipped", None)


def test_reschedule_moves_end_date_and_clears_reminded_at(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    rice = calendar_farm.cycle_ids["Field B"]
    basal = _task(db, rice, "Basal fertilizer")
    basal.reminder = True
    basal.reminded_at = datetime.now(UTC)
    db.commit()
    new_date = basal.scheduled_date + 3 * DAY

    body = _patch(
        client, member_token, basal.activity_id, {"scheduled_date": new_date.isoformat()}
    ).json()

    assert body["status"] == "rescheduled"
    assert body["scheduled_date"] == new_date.isoformat()
    assert body["end_date"] == (basal.end_date + 3 * DAY).isoformat()
    db.expire_all()
    assert db.get(CropActivity, basal.activity_id).reminded_at is None


def test_a_new_time_is_a_reschedule_but_a_done_task_stays_done(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    tasks = _tasks(db, calendar_farm.cycle_ids["Field A"])
    timed = _patch(client, member_token, tasks[0].activity_id, {"scheduled_time": "07:00"}).json()
    assert timed["status"] == "rescheduled"

    _patch(client, member_token, tasks[1].activity_id, {"status": "done"})
    moved = _patch(
        client,
        member_token,
        tasks[1].activity_id,
        {"scheduled_date": (tasks[1].scheduled_date + DAY).isoformat()},
    ).json()
    assert moved["status"] == "done"

    same = _patch(
        client,
        member_token,
        tasks[2].activity_id,
        {"scheduled_date": tasks[2].scheduled_date.isoformat()},
    ).json()
    assert same["status"] == "pending"  # the same date is not a reschedule


def test_notes_and_reminder_on_a_generated_task(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    task = _tasks(db, calendar_farm.cycle_ids["Field A"])[0]
    body = _patch(
        client,
        member_token,
        task.activity_id,
        {"notes": "Bought urea at the coop store", "reminder": True},
    ).json()
    assert (body["notes"], body["reminder"], body["status"]) == (
        "Bought urea at the coop store",
        True,
        "pending",
    )
    cleared = _patch(client, member_token, task.activity_id, {"notes": None}).json()
    assert cleared["notes"] is None


def test_title_and_stage_only_on_custom_tasks(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    generated = _tasks(db, corn)[0]
    for body in ({"title": "Renamed"}, {"growth_stage": "harvest"}):
        response = _patch(client, member_token, generated.activity_id, body)
        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "not_editable"}}

    custom = _custom(client, member_token, corn).json()
    edited = _patch(
        client, member_token, custom["activity_id"], {"title": "Renamed", "growth_stage": "harvest"}
    ).json()
    assert (edited["title"], edited["growth_stage"]) == ("Renamed", "harvest")


def test_patch_errors(
    client: TestClient, db, member_token: str, outsider_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    task = _tasks(db, corn)[0]

    response = _patch(client, outsider_token, task.activity_id, {"status": "done"})
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "activity_not_found"}}
    assert _patch(client, member_token, 999999, {"status": "done"}).status_code == 404

    far = task.scheduled_date.replace(year=task.scheduled_date.year + 3).isoformat()
    response = _patch(client, member_token, task.activity_id, {"scheduled_date": far})
    assert response.json() == {"detail": {"code": "date_out_of_range"}}

    db.get(CropCycle, corn).status = "harvested"
    db.commit()
    response = _patch(client, member_token, task.activity_id, {"status": "done"})
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cycle_closed"}}


@pytest.mark.parametrize(
    "body",
    [
        {"status": "rescheduled"},
        {"status": None},
        {"scheduled_date": None},
        {"reminder": None},
        {"title": None},
        {"cycle_id": 1},
        {"notes": "x" * 501},
    ],
)
def test_patch_bad_bodies_get_fastapi_422(
    client: TestClient, db, member_token: str, calendar_farm, body: dict
) -> None:
    task = _tasks(db, calendar_farm.cycle_ids["Field A"])[0]
    response = _patch(client, member_token, task.activity_id, body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# ---------- DELETE /activities/{activity_id} ----------


def test_deletes_a_custom_task_with_its_reminders(
    client: TestClient, db, member_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    custom = _custom(client, member_token, corn).json()
    owner = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    db.add(
        Notification(
            user_id=owner.user_id,
            farm_id=calendar_farm.farm_id,
            activity_id=custom["activity_id"],
            type="task_reminder",
            title="Task today: Check field water level",
            body="Field A: Check field water level, Nov 12",
        )
    )
    slot = WeatherLog(
        farm_id=calendar_farm.farm_id,
        forecast_for=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        is_forecast=True,
        condition_code=500,
    )
    db.add(slot)
    db.flush()
    rule = db.scalar(select(AlertRule).order_by(AlertRule.rule_id))
    alert = WeatherAlert(
        rule_id=rule.rule_id,
        farm_id=calendar_farm.farm_id,
        weather_id=slot.weather_id,
        activity_id=custom["activity_id"],
        message="Kept text",
        severity="info",
        issued_at=datetime.now(UTC),
    )
    db.add(alert)
    db.commit()

    response = client.delete(_task_url(custom["activity_id"]), headers=auth_header(member_token))

    assert response.status_code == 204
    db.expire_all()
    assert db.get(CropActivity, custom["activity_id"]) is None
    assert db.scalars(select(Notification)).all() == []
    kept = db.get(WeatherAlert, alert.alert_id)
    assert (kept.activity_id, kept.message) == (None, "Kept text")


def test_delete_errors(
    client: TestClient, db, member_token: str, outsider_token: str, calendar_farm
) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    generated = _tasks(db, corn)[0]
    custom = _custom(client, member_token, corn).json()

    response = client.delete(_task_url(generated.activity_id), headers=auth_header(member_token))
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "generated_task"}}

    response = client.delete(_task_url(custom["activity_id"]), headers=auth_header(outsider_token))
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "activity_not_found"}}

    db.get(CropCycle, corn).status = "harvested"
    db.commit()
    response = client.delete(_task_url(custom["activity_id"]), headers=auth_header(member_token))
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "cycle_closed"}}


def test_workers_can_change_tasks_too(client: TestClient, db, worker: str, calendar_farm) -> None:
    corn = calendar_farm.cycle_ids["Field A"]
    custom = _custom(client, worker, corn).json()
    assert (
        client.delete(_task_url(custom["activity_id"]), headers=auth_header(worker)).status_code
        == 204
    )
    assert db.scalar(select(User.user_id).where(User.mobile_no == WORKER_MOBILE)) is not None
