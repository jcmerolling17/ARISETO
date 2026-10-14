from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db.session import engine

EXPECTED_TABLES = {
    "users",
    "barangay",
    "farm",
    "farm_assignment",
    "crop",
    "crop_variety",
    "crop_cycle",
    "calendar_template_task",
    "crop_activity",
    "weather_log",
}


def test_health_reports_ok_when_database_answers(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_migration_creates_all_tables() -> None:
    tables = set(inspect(engine).get_table_names())

    assert EXPECTED_TABLES <= tables


def test_frontend_is_served_in_development(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "ARISETO" in response.text
