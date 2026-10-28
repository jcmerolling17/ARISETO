"""Test setup: point the app at TEST_DATABASE_URL, migrate it once, empty it per test."""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings

_settings = get_settings()
if not _settings.test_database_url:
    raise RuntimeError("Set TEST_DATABASE_URL in .env before running the tests.")
if _settings.test_database_url == _settings.database_url:
    raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL; tests empty every table.")

# Must happen before app.db.session is imported, since it builds the engine at import time.
os.environ["DATABASE_URL"] = _settings.test_database_url
get_settings.cache_clear()

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    """Alembic pointed at the test database."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Run the real migration on the test database (down then up), once per test run."""
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    engine.dispose()


# Reference rows seeded by the migrations; kept between tests.
SEEDED_TABLES = {"crop"}


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    tables = ", ".join(
        table.name for table in Base.metadata.sorted_tables if table.name not in SEEDED_TABLES
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def no_real_weather(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never use the real OpenWeatherMap key or network: the key read from .env is
    cleared, and a client the code builds itself refuses every request. Tests that fetch
    set a fake key and pass or patch in an httpx2 MockTransport client."""
    import httpx2

    from app.services import openweathermap_service

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("tests must not call OpenWeatherMap")

    monkeypatch.setattr(get_settings(), "openweathermap_api_key", None)
    monkeypatch.setattr(
        openweathermap_service,
        "make_client",
        lambda: httpx2.Client(
            timeout=openweathermap_service.TIMEOUT_SECONDS,
            transport=httpx2.MockTransport(refuse),
        ),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


ADMIN_PASSWORD = "admin-pass-123"
MEMBER_PASSWORD = "secret123"


def member_payload(**overrides: object) -> dict:
    """A valid POST /auth/register body, as js/api/client.js sends it."""
    payload = {
        "first_name": "Ma. Cristina",
        "last_name": "Dela Cruz",
        "mobile_no": "+639171234567",
        "email": "cristina@example.com",
        "password": MEMBER_PASSWORD,
        "member_no": "MPMPC-0042",
        "municipality": "Sablayan",
        "barangay_id": None,
        "preferred_language": "fil",
        "accepted_terms": True,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def admin_token(client: TestClient, db) -> str:
    """Bearer token for an active coop_admin created through the service layer."""
    from app.services import auth_service

    auth_service.create_admin(
        db,
        first_name="Maria",
        last_name="Santos",
        mobile_no="+639990000001",
        password=ADMIN_PASSWORD,
        municipality="San Jose",
    )
    response = client.post(
        "/api/v1/auth/login", json={"mobile_no": "+639990000001", "password": ADMIN_PASSWORD}
    )
    return response.json()["access_token"]


def login_token(client: TestClient, mobile_no: str, password: str) -> str:
    body = {"mobile_no": mobile_no, "password": password}
    response = client.post("/api/v1/auth/login", json=body)
    return response.json()["access_token"]


def create_active_member(db, **overrides: object):
    """An approved member account, created through the service layer like a real sign-up."""
    from app.models.enums import AccountStatus
    from app.schemas.auth import RegisterRequest
    from app.services import auth_service

    user = auth_service.register_member(db, RegisterRequest(**member_payload(**overrides)))
    user.account_status = AccountStatus.ACTIVE
    db.commit()
    return user


@pytest.fixture
def member_token(client: TestClient, db) -> str:
    """Bearer token for an active member."""
    create_active_member(db)
    return login_token(client, "+639171234567", MEMBER_PASSWORD)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Rows copied from the seed data (barangays.csv and varieties.csv), so tests use real values.
TANGKALAN = {
    "psgc_code": "1705106006",
    "municipality": "Mamburao",
    "barangay_name": "Tangkalan",
    "center_latitude": Decimal("13.271995"),
    "center_longitude": Decimal("120.624727"),
}
VARIETIES = {  # variety_name: (crop_name, maturity_class, maturity_days)
    "NK6410": ("Corn", "early", 90),
    "RC-402": ("Rice", "early", 110),
    "C4-GREEN": ("Rice", "very_early", 100),
}


@pytest.fixture
def barangay_id(db) -> int:
    from app.models import Barangay

    barangay = Barangay(**TANGKALAN)
    db.add(barangay)
    db.commit()
    return barangay.barangay_id


@pytest.fixture
def variety_ids(db) -> dict[str, int]:
    """variety_name -> variety_id for the VARIETIES rows."""
    from sqlalchemy import select

    from app.models import Crop, CropVariety

    crop_ids = {crop.crop_name: crop.crop_id for crop in db.scalars(select(Crop))}
    rows = [
        CropVariety(
            crop_id=crop_ids[crop],
            variety_name=name,
            maturity_class=maturity_class,
            maturity_days=days,
        )
        for name, (crop, maturity_class, days) in VARIETIES.items()
    ]
    db.add_all(rows)
    db.commit()
    return {row.variety_name: row.variety_id for row in rows}
