import pytest
from sqlalchemy import select

from app import cli
from app.core.security import verify_password
from app.models import User
from app.models.enums import AccountStatus, UserRole

ARGS = [
    "create-admin",
    "--first-name", "Maria",
    "--last-name", "Santos",
    "--mobile-no", "+639990000009",
    "--municipality", "San Jose",
]


def _answer_passwords(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    replies = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt="": next(replies))


def test_create_admin_creates_active_coop_admin(monkeypatch, db, capsys) -> None:
    _answer_passwords(monkeypatch, "admin-pass-123", "admin-pass-123")

    assert cli.main(ARGS) == 0

    admin = db.scalar(select(User).where(User.mobile_no == "+639990000009"))
    assert admin.role == UserRole.COOP_ADMIN
    assert admin.account_status == AccountStatus.ACTIVE
    assert admin.member_no is None
    assert verify_password("admin-pass-123", admin.password_hash)
    assert "Created coop_admin" in capsys.readouterr().out


def test_create_admin_rejects_mismatched_passwords(monkeypatch, db) -> None:
    _answer_passwords(monkeypatch, "admin-pass-123", "different-pass")

    assert cli.main(ARGS) == 1
    assert db.scalar(select(User)) is None


@pytest.mark.parametrize(
    ("replace", "password"),
    [
        (("--mobile-no", "09990000009"), "admin-pass-123"),
        (("--municipality", "Calapan"), "admin-pass-123"),
        (None, "short"),
    ],
)
def test_create_admin_validates_input(monkeypatch, db, capsys, replace, password) -> None:
    args = list(ARGS)
    if replace:
        args[args.index(replace[0]) + 1] = replace[1]
    _answer_passwords(monkeypatch, password, password)

    assert cli.main(args) == 1
    assert db.scalar(select(User)) is None
    assert capsys.readouterr().err


def test_create_admin_refuses_duplicate_mobile(monkeypatch, db, capsys) -> None:
    _answer_passwords(monkeypatch, *["admin-pass-123"] * 4)
    assert cli.main(ARGS) == 0

    assert cli.main(ARGS) == 1
    assert "mobile_taken" in capsys.readouterr().err
