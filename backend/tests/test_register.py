import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import verify_password
from app.models import Barangay, User
from app.models.enums import AccountStatus, LanguageCode, UserRole
from tests.conftest import MEMBER_PASSWORD, member_payload

URL = "/api/v1/auth/register"


def _seed_barangay(
    db, municipality: str = "Sablayan", name: str = "Poblacion", psgc_code: str = "1751700001"
) -> int:
    barangay = Barangay(
        psgc_code=psgc_code,
        municipality=municipality,
        barangay_name=name,
        center_latitude=12.836,
        center_longitude=120.777,
    )
    db.add(barangay)
    db.commit()
    return barangay.barangay_id


def test_register_creates_pending_member(client: TestClient, db) -> None:
    response = client.post(URL, json=member_payload())

    assert response.status_code == 201
    body = response.json()
    assert body == {"user_id": body["user_id"], "account_status": "pending"}

    user = db.scalar(select(User).where(User.user_id == body["user_id"]))
    assert user.role == UserRole.MEMBER
    assert user.account_status == AccountStatus.PENDING
    assert user.preferred_language == LanguageCode.FIL
    assert user.first_name == "Ma. Cristina"
    assert user.password_hash != MEMBER_PASSWORD
    assert user.password_hash.startswith("$argon2")
    assert verify_password(MEMBER_PASSWORD, user.password_hash)


def test_register_normalizes_email_member_no_and_names(client: TestClient, db) -> None:
    response = client.post(
        URL,
        json=member_payload(
            email="Cristina@Example.COM", member_no="  mpmpc-0042 ", first_name="  Ma.   Cristina "
        ),
    )

    assert response.status_code == 201
    user = db.get(User, response.json()["user_id"])
    assert user.email == "cristina@example.com"
    assert user.member_no == "MPMPC-0042"
    assert user.first_name == "Ma. Cristina"


def test_register_without_optional_fields_uses_defaults(client: TestClient, db) -> None:
    payload = member_payload()
    for optional in ("email", "barangay_id", "preferred_language"):
        payload.pop(optional)

    response = client.post(URL, json=payload)

    assert response.status_code == 201
    user = db.get(User, response.json()["user_id"])
    assert user.email is None
    assert user.barangay_id is None
    assert user.preferred_language == LanguageCode.FIL


def test_register_with_barangay_in_chosen_municipality(client: TestClient, db) -> None:
    barangay_id = _seed_barangay(db)

    response = client.post(URL, json=member_payload(barangay_id=barangay_id))

    assert response.status_code == 201
    assert db.get(User, response.json()["user_id"]).barangay_id == barangay_id


@pytest.mark.parametrize(
    ("field", "conflicting_value", "code"),
    [
        ("mobile_no", "+639171234567", "mobile_taken"),
        ("email", "CRISTINA@example.com", "email_taken"),
        ("member_no", "mpmpc-0042", "member_no_taken"),
    ],
)
def test_register_conflicts_return_409_codes(
    client: TestClient, field: str, conflicting_value: str, code: str
) -> None:
    assert client.post(URL, json=member_payload()).status_code == 201
    unique = {"mobile_no": "+639180000000", "email": "other@example.com", "member_no": "MPMPC-9"}
    unique[field] = conflicting_value

    response = client.post(URL, json=member_payload(**unique))

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": code}}


def test_register_barangay_from_other_municipality_is_rejected(client: TestClient, db) -> None:
    other_barangay = _seed_barangay(
        db, municipality="San Jose", name="Labangan", psgc_code="1751800001"
    )

    response = client.post(URL, json=member_payload(barangay_id=other_barangay))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "barangay_municipality_mismatch"}}


def test_register_unknown_barangay_is_rejected(client: TestClient) -> None:
    response = client.post(URL, json=member_payload(barangay_id=999))

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "barangay_municipality_mismatch"}}


@pytest.mark.parametrize(
    "overrides",
    [
        {"mobile_no": "09171234567"},
        {"mobile_no": "+63917123456"},
        {"mobile_no": "+638171234567"},
        {"password": "short"},
        {"municipality": "Calapan"},
        {"email": "not-an-email"},
        {"first_name": ""},
        {"first_name": "x" * 61},
        {"last_name": "   "},
        {"member_no": ""},
        {"member_no": "x" * 21},
        {"preferred_language": "es"},
        {"role": "coop_admin"},
        {"account_status": "active"},
    ],
)
def test_register_invalid_fields_use_fastapi_422(client: TestClient, overrides: dict) -> None:
    response = client.post(URL, json=member_payload(**overrides))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("missing", ["first_name", "last_name", "mobile_no", "password",
                                     "member_no", "municipality"])
def test_register_missing_required_field_is_422(client: TestClient, missing: str) -> None:
    payload = member_payload()
    payload.pop(missing)

    response = client.post(URL, json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", missing]
