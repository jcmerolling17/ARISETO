import pytest
from fastapi.testclient import TestClient

from app.models import Barangay

URL = "/api/v1/barangays"


def test_empty_table_returns_empty_list(client: TestClient) -> None:
    response = client.get(URL, params={"municipality": "Sablayan"})

    assert response.status_code == 200
    assert response.json() == []


def test_lists_only_that_municipality_sorted_by_name(client: TestClient, db) -> None:
    db.add_all(
        [
            Barangay(psgc_code="1", municipality="Sablayan", barangay_name="Tuban",
                     center_latitude=12.9, center_longitude=120.8),
            Barangay(psgc_code="2", municipality="Sablayan", barangay_name="Poblacion",
                     center_latitude=12.836, center_longitude=120.777),
            Barangay(psgc_code="3", municipality="San Jose", barangay_name="Labangan",
                     center_latitude=12.35, center_longitude=121.07),
        ]
    )
    db.commit()

    response = client.get(URL, params={"municipality": "Sablayan"})

    assert response.status_code == 200
    body = response.json()
    assert [row["barangay_name"] for row in body] == ["Poblacion", "Tuban"]
    assert body[0] == {
        "barangay_id": body[0]["barangay_id"],
        "barangay_name": "Poblacion",
        "center_latitude": 12.836,
        "center_longitude": 120.777,
    }


def test_is_public(client: TestClient) -> None:
    response = client.get(URL, params={"municipality": "Looc"}, headers={})

    assert response.status_code == 200


@pytest.mark.parametrize("municipality", ["Calapan", "sablayan", ""])
def test_unknown_municipality_returns_422_code(client: TestClient, municipality: str) -> None:
    response = client.get(URL, params={"municipality": municipality})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "unknown_municipality"}}


def test_missing_municipality_is_fastapi_422(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "municipality"]
