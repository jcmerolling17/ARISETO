"""Migration round trips (0003 and 0004): upgrade, downgrade, and upgrade again on the test
database."""

from datetime import date

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.db.session import engine
from tests.conftest import alembic_config, auth_header, member_payload


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _maturity_classes() -> list[str]:
    with engine.connect() as connection:
        return (
            connection.execute(text("SELECT unnest(enum_range(NULL::maturity_class))::text"))
            .scalars()
            .all()
        )


def _has_planting_method_type() -> bool:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'planting_method')")
        ).scalar()


def _assert_head_schema() -> None:
    assert _columns("field") == {"field_id", "farm_id", "field_name", "area_ha", "created_at"}
    assert "field_id" in _columns("crop_cycle")
    assert "farm_id" not in _columns("crop_cycle")
    assert _maturity_classes() == ["very_early", "early", "medium", "late"]
    assert not _has_planting_method_type()


ACCOUNT_COLUMNS = {"terms_accepted_at", "deletion_requested_at", "password_changed_at"}
MONEY_TABLES = {"expense_category", "expense", "harvest_record"}


def _tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def _category_names() -> list[str]:
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT category_name FROM expense_category ORDER BY category_id")
            )
            .scalars()
            .all()
        )


def _has_quantity_unit_type() -> bool:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'quantity_unit')")
        ).scalar()


def test_0005_upgrade_downgrade_upgrade_seeds_the_seven_categories(db) -> None:
    db.close()
    config = alembic_config()
    assert MONEY_TABLES <= _tables()

    command.downgrade(config, "0004")
    try:
        assert not MONEY_TABLES & _tables()
        assert not _has_quantity_unit_type()
    finally:
        command.upgrade(config, "head")

    assert MONEY_TABLES <= _tables()
    assert _has_quantity_unit_type()
    assert _category_names() == [
        "Seeds",
        "Fertilizer",
        "Chemicals",
        "Labor",
        "Equipment",
        "Fuel",
        "Others",
    ]


def test_0004_upgrade_downgrade_upgrade_keeps_accounts(client: TestClient, db) -> None:
    user_id = client.post("/api/v1/auth/register", json=member_payload()).json()["user_id"]
    db.close()
    config = alembic_config()
    assert ACCOUNT_COLUMNS <= _columns("users")

    command.downgrade(config, "0003")
    try:
        assert not ACCOUNT_COLUMNS & _columns("users")
        with engine.connect() as connection:
            kept = connection.execute(
                text("SELECT user_id FROM users WHERE mobile_no = '+639171234567'")
            ).scalar()
        assert kept == user_id
    finally:
        command.upgrade(config, "head")

    assert ACCOUNT_COLUMNS <= _columns("users")
    with engine.connect() as connection:
        values = connection.execute(
            text(
                "SELECT terms_accepted_at, deletion_requested_at, password_changed_at "
                "FROM users WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        ).one()
    # Upgrading again adds the columns empty, as for accounts created before Phase 6.
    assert tuple(values) == (None, None, None)


def test_upgrade_downgrade_upgrade(db) -> None:
    db.close()
    config = alembic_config()
    _assert_head_schema()

    command.downgrade(config, "0002")
    try:
        assert {"crop_id", "variety_name", "planting_date", "planting_method", "season"} <= (
            _columns("field")
        )
        assert "farm_id" in _columns("crop_cycle")
        assert "field_id" not in _columns("crop_cycle")
        assert _maturity_classes() == ["early", "medium", "late"]
        assert _has_planting_method_type()
    finally:
        command.upgrade(config, "head")

    _assert_head_schema()


def test_downgrade_copies_each_fields_first_cycle_back(
    client: TestClient, db, member_token: str, barangay_id: int, variety_ids
) -> None:
    sown = date.today()
    body = {
        "farm_name": "MPMPC Farm",
        "barangay_id": barangay_id,
        "season": "wet",
        "fields": [
            {
                "field_name": "Field A",
                "area_ha": 1.25,
                "variety_id": variety_ids["NK6410"],
                "planting_date": sown.isoformat(),
            }
        ],
    }
    farm_id = client.post("/api/v1/farms", json=body, headers=auth_header(member_token)).json()[
        "farm_id"
    ]
    db.close()
    config = alembic_config()
    # The old maturity_class has no 'very_early', so downgrade refuses such varieties.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM crop_variety WHERE maturity_class = 'very_early'"))

    command.downgrade(config, "0002")
    try:
        with engine.connect() as connection:
            field = connection.execute(
                text(
                    "SELECT c.crop_name, f.variety_name, f.planting_date, "
                    "f.planting_method::text, f.season::text "
                    "FROM field f JOIN crop c USING (crop_id)"
                )
            ).one()
            cycle_farm = connection.execute(text("SELECT farm_id FROM crop_cycle")).scalar()
        assert tuple(field) == ("Corn", "NK6410", sown, "direct_seeding", "wet")
        assert cycle_farm == farm_id
    finally:
        # Upgrading can't tell which field an old cycle belongs to, so clear the farm first.
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE farm, farm_assignment, field, crop_cycle, crop_activity CASCADE")
            )
        command.upgrade(config, "head")

    _assert_head_schema()


ALERT_TABLES = {"alert_rule", "weather_alert", "notification"}
ALERT_TYPES = (
    "alert_parameter",
    "alert_operator",
    "alert_severity",
    "alert_aggregation",
    "notification_type",
)


def _existing_types(names: tuple[str, ...]) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT typname FROM pg_type WHERE typname = ANY(:names)"),
                {"names": list(names)},
            ).scalars()
        )


def _rules() -> list[tuple]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT rule_name, parameter::text, aggregation::text, operator::text, "
                    "threshold, lookahead_hours, severity::text, is_active "
                    "FROM alert_rule ORDER BY rule_id"
                )
            )
        ]


def test_0006_upgrade_downgrade_upgrade_seeds_the_seven_rules(db) -> None:
    from decimal import Decimal

    db.close()
    config = alembic_config()
    assert ALERT_TABLES <= _tables()

    command.downgrade(config, "0005")
    try:
        assert not ALERT_TABLES & _tables()
        assert _existing_types(ALERT_TYPES) == set()
        assert MONEY_TABLES <= _tables()
    finally:
        command.upgrade(config, "head")

    assert ALERT_TABLES <= _tables()
    assert _existing_types(ALERT_TYPES) == set(ALERT_TYPES)
    assert _rules() == [
        (
            "Heavy rain: PAGASA yellow level",
            "rain_mm",
            "sum",
            ">=",
            Decimal("50.00"),
            24,
            "info",
            True,
        ),
        (
            "Heavy rain: PAGASA orange level",
            "rain_mm",
            "sum",
            ">=",
            Decimal("100.00"),
            24,
            "warning",
            True,
        ),
        (
            "Heavy rain: PAGASA red level",
            "rain_mm",
            "sum",
            ">",
            Decimal("200.00"),
            24,
            "critical",
            True,
        ),
        (
            "Heat index: Extreme Caution",
            "heat_index_c",
            "max",
            ">=",
            Decimal("33.00"),
            24,
            "info",
            False,
        ),
        ("Heat index: Danger", "heat_index_c", "max", ">=", Decimal("42.00"), 24, "warning", True),
        (
            "Heat index: Extreme Danger",
            "heat_index_c",
            "max",
            ">=",
            Decimal("52.00"),
            24,
            "critical",
            True,
        ),
        ("Strong wind", "wind_speed_mps", "max", ">=", Decimal("10.83"), 24, "warning", True),
    ]


TEMPLATE_NEW = {
    "anchor",
    "day_offset",
    "day_offset_end",
    "repeat_every_days",
    "repeat_until_anchor",
    "repeat_until_offset",
    "growth_stage",
    "source_reference",
}
ACTIVITY_NEW = {
    "end_date",
    "scheduled_time",
    "reminder",
    "reminded_at",
    "notes",
    "task_type",
    "growth_stage",
    "is_weather_sensitive",
}


def test_0007_upgrade_downgrade_upgrade(db) -> None:
    db.close()
    config = alembic_config()
    assert TEMPLATE_NEW <= _columns("calendar_template_task")
    assert "week_no" not in _columns("calendar_template_task")

    command.downgrade(config, "0006")
    try:
        assert not TEMPLATE_NEW & _columns("calendar_template_task")
        assert "week_no" in _columns("calendar_template_task")
        assert not ACTIVITY_NEW & _columns("crop_activity")
        assert "activity_id" not in _columns("notification")
        assert _existing_types(("calendar_anchor", "growth_stage")) == set()
    finally:
        command.upgrade(config, "head")

    assert TEMPLATE_NEW <= _columns("calendar_template_task")
    assert ACTIVITY_NEW <= _columns("crop_activity")
    assert "activity_id" in _columns("notification")
    assert _existing_types(("calendar_anchor", "growth_stage")) == {
        "calendar_anchor",
        "growth_stage",
    }


def test_0007_checks(db) -> None:
    """The documented checks: a range never ends before it starts, the repeat columns go
    together, and activity_id is set exactly for a task_reminder."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    statements = [
        "INSERT INTO crop_activity (cycle_id, title, scheduled_date, end_date, client_uuid) "
        "VALUES (1, 't', '2026-11-10', '2026-11-09', gen_random_uuid())",
        "INSERT INTO notification (user_id, type, title, body) "
        "VALUES (1, 'task_reminder', 't', 'b')",
    ]
    for statement in statements:
        with engine.connect() as connection, pytest.raises(IntegrityError):
            connection.execute(text(statement))
    with engine.connect() as connection:
        checks = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = "
                    "'calendar_template_task'::regclass AND contype = 'c'"
                )
            ).scalars()
        )
    assert {
        "ck_calendar_template_task_day_offset_end_order",
        "ck_calendar_template_task_repeat_columns_together",
        "ck_calendar_template_task_repeat_every_days_positive",
    } <= checks
