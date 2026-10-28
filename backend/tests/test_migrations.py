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
