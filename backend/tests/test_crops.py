from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Crop, User
from app.models.enums import AccountStatus
from tests.conftest import auth_header

URL = "/api/v1/crops"


def test_lists_crops_with_their_varieties(
    client: TestClient, db, member_token: str, variety_ids: dict[str, int]
) -> None:
    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 200
    crop_ids = {crop.crop_name: crop.crop_id for crop in db.scalars(select(Crop))}
    assert response.json() == [
        {
            "crop_id": crop_ids["Corn"],
            "crop_name": "Corn",
            "varieties": [
                {
                    "variety_id": variety_ids["NK6410"],
                    "variety_name": "NK6410",
                    "maturity_class": "early",
                    "maturity_days": 90,
                }
            ],
        },
        {"crop_id": crop_ids["Onion"], "crop_name": "Onion", "varieties": []},
        {
            "crop_id": crop_ids["Rice"],
            "crop_name": "Rice",
            "varieties": [
                {
                    "variety_id": variety_ids["C4-GREEN"],
                    "variety_name": "C4-GREEN",
                    "maturity_class": "very_early",
                    "maturity_days": 100,
                },
                {
                    "variety_id": variety_ids["RC-402"],
                    "variety_name": "RC-402",
                    "maturity_class": "early",
                    "maturity_days": 110,
                },
            ],
        },
    ]


def test_coop_admin_can_list_crops(client: TestClient, admin_token: str) -> None:
    response = client.get(URL, headers=auth_header(admin_token))

    assert response.status_code == 200
    assert [crop["crop_name"] for crop in response.json()] == ["Corn", "Onion", "Rice"]


def test_requires_login(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "not_authenticated"}}


def test_deactivated_account_is_refused(client: TestClient, db, member_token: str) -> None:
    member = db.scalar(select(User).where(User.mobile_no == "+639171234567"))
    member.account_status = AccountStatus.DEACTIVATED
    db.commit()

    response = client.get(URL, headers=auth_header(member_token))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_deactivated"}}
