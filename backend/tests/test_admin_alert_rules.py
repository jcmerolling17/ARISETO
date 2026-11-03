"""GET /admin/alert-rules and PATCH /admin/alert-rules/{rule_id}: the seven seeded PAGASA
rules, and the changes an administrator may make."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import WeatherAlert, WeatherLog
from app.services import alert_service
from tests.conftest import auth_header

URL = "/api/v1/admin/alert-rules"

RAIN = "about {value} mm of rain is forecast in the next {hours} hours."
HEAT = "the heat index may reach {value} °C in the next {hours} hours."
SEEDED = [
    # rule_name, parameter, aggregation, operator, threshold, severity, is_active, source,
    # message_template
    ("Heavy rain: PAGASA yellow level", "rain_mm", "sum", ">=", 50, "info", True,
     "PAGASA weather advisory: 50 to 100 mm in 24 hours",
     f"Rain alert (PAGASA yellow level, 50 to 100 mm): {RAIN}"),
    ("Heavy rain: PAGASA orange level", "rain_mm", "sum", ">=", 100, "warning", True,
     "PAGASA weather advisory: 100 to 200 mm",
     f"Rain alert (PAGASA orange level, 100 to 200 mm): {RAIN}"),
    ("Heavy rain: PAGASA red level", "rain_mm", "sum", ">", 200, "critical", True,
     "PAGASA weather advisory: more than 200 mm",
     f"Rain alert (PAGASA red level, more than 200 mm): {RAIN}"),
    ("Heat index: Extreme Caution", "heat_index_c", "max", ">=", 33, "info", False,
     "PAGASA heat index classification: 33 to 41 °C",
     f"Heat index alert (PAGASA Extreme Caution, 33 to 41 °C): {HEAT}"),
    ("Heat index: Danger", "heat_index_c", "max", ">=", 42, "warning", True,
     "PAGASA heat index classification: 42 to 51 °C",
     f"Heat index alert (PAGASA Danger, 42 to 51 °C): {HEAT}"),
    ("Heat index: Extreme Danger", "heat_index_c", "max", ">=", 52, "critical", True,
     "PAGASA heat index classification: 52 °C and above",
     f"Heat index alert (PAGASA Extreme Danger, 52 °C and above): {HEAT}"),
    ("Strong wind", "wind_speed_mps", "max", ">=", 10.83, "warning", True,
     "PAGASA tropical cyclone wind signals: strong winds, 39 to 61 km/h "
     "(press release, 23 March 2022)",
     "Strong wind alert (PAGASA strong winds, 39 km/h and up): winds of up to {value} km/h "
     "are forecast in the next {hours} hours."),
]  # fmt: skip


def test_lists_the_seven_seeded_rules(client: TestClient, admin_token: str) -> None:
    response = client.get(URL, headers=auth_header(admin_token))

    assert response.status_code == 200
    rules = response.json()
    assert [rule["rule_id"] for rule in rules] == list(range(1, 8))
    for rule, seeded in zip(rules, SEEDED, strict=True):
        name, parameter, aggregation, operator, threshold, severity, active, source, message = (
            seeded
        )
        assert rule == {
            "rule_id": rule["rule_id"],
            "rule_name": name,
            "parameter": parameter,
            "aggregation": aggregation,
            "operator": operator,
            "threshold": threshold,
            "lookahead_hours": 24,
            "severity": severity,
            "message_template": message,
            "source_reference": source,
            "is_active": active,
        }


def test_members_are_not_admins(client: TestClient, member_token: str) -> None:
    for response in (
        client.get(URL, headers=auth_header(member_token)),
        client.patch(f"{URL}/1", json={"is_active": False}, headers=auth_header(member_token)),
    ):
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "not_admin"}}


def _patch(client: TestClient, token: str, rule_id: int, body: dict):
    return client.patch(f"{URL}/{rule_id}", json=body, headers=auth_header(token))


def test_updates_the_editable_fields(client: TestClient, admin_token: str) -> None:
    template = "Rain: {value} mm in {hours} h."
    response = _patch(
        client,
        admin_token,
        1,
        {"is_active": False, "threshold": 60.5, "message_template": template},
    )

    assert response.status_code == 200
    rule = response.json()
    assert (rule["is_active"], rule["threshold"], rule["message_template"]) == (
        False,
        60.5,
        template,
    )
    assert client.get(URL, headers=auth_header(admin_token)).json()[0] == rule


def test_only_sent_fields_change(client: TestClient, admin_token: str) -> None:
    rule = _patch(client, admin_token, 4, {"is_active": True}).json()
    assert rule["is_active"] is True
    assert rule["threshold"] == 33
    assert rule["message_template"] == SEEDED[3][8]


@pytest.mark.parametrize(
    "template",
    [
        "Plain text with no placeholders.",
        "{value}",
        "{hours} hours, {value} mm, {value} again",
    ],
)
def test_valid_templates(client: TestClient, admin_token: str, template: str) -> None:
    response = _patch(client, admin_token, 1, {"message_template": template})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "template",
    [
        "About {amount} mm",
        "{value} {farm}",
        "Open { brace",
        "close } brace",
        "{Value}",
        "{{value}}",
    ],
)
def test_other_placeholders_are_invalid(
    client: TestClient, admin_token: str, template: str
) -> None:
    response = _patch(client, admin_token, 1, {"message_template": template})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_template"}}
    assert (
        client.get(URL, headers=auth_header(admin_token)).json()[0]["message_template"]
        == (SEEDED[0][8])
    )


def test_unknown_rule(client: TestClient, admin_token: str) -> None:
    response = _patch(client, admin_token, 99, {"message_template": "{bad}"})
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "rule_not_found"}}


@pytest.mark.parametrize(
    "body",
    [
        {"threshold": 0},
        {"threshold": -5},
        {"threshold": 10000},
        {"threshold": 1.234},
        {"threshold": None},
        {"is_active": None},
        {"is_active": "yes"},
        {"message_template": None},
        {"message_template": "   "},
        {"lookahead_hours": 12},
        {"rule_name": "Renamed"},
    ],
)
def test_invalid_bodies_get_fastapi_422(client: TestClient, admin_token: str, body: dict) -> None:
    response = _patch(client, admin_token, 1, body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_a_change_applies_from_the_next_evaluation(
    client: TestClient, db, admin_token: str, farm
) -> None:
    now = datetime(2026, 11, 3, tzinfo=UTC)
    db.add(
        WeatherLog(
            farm_id=farm.farm_id,
            forecast_for=now + timedelta(hours=3),
            fetched_at=now,
            is_forecast=True,
            rain_mm=Decimal("60"),
            condition_code=500,
        )
    )
    db.commit()
    alert_service.evaluate_farm(db, farm.farm_id, now)
    db.commit()
    [issued] = db.scalars(select(WeatherAlert)).all()

    _patch(client, admin_token, 1, {"message_template": "Changed {value}"})

    db.expire_all()
    assert db.get(WeatherAlert, issued.alert_id).message.startswith("Rain alert (PAGASA yellow")
    assert _patch(client, admin_token, 2, {"threshold": 55}).status_code == 200
    later = now + timedelta(hours=1)
    db.add(
        WeatherLog(
            farm_id=farm.farm_id,
            forecast_for=later + timedelta(hours=3),
            fetched_at=later,
            is_forecast=True,
            rain_mm=Decimal("60"),
            condition_code=500,
        )
    )
    db.commit()
    # Orange now starts at 55 mm, above the yellow alert already issued, so it is issued.
    [orange] = alert_service.evaluate_farm(db, farm.farm_id, later)
    assert orange.rule_id == 2
