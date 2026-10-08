"""Command line tasks.

Create the first cooperative administrator (run from backend/ with the venv active):

    python -m app.cli create-admin --first-name Maria --last-name Santos \
        --mobile-no +639171234567 --municipality "San Jose"

The password is asked for twice and never echoed.
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app.core.errors import AppError
from app.db.session import SessionLocal
from app.schemas.admin import AdminCreate
from app.services import auth_service


def _create_admin(args: argparse.Namespace) -> int:
    password = getpass.getpass("Password (8+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        data = AdminCreate(
            first_name=args.first_name,
            last_name=args.last_name,
            mobile_no=args.mobile_no,
            email=args.email,
            password=password,
            municipality=args.municipality,
        )
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"])
            print(f"{field}: {error['msg']}", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        try:
            user = auth_service.create_admin(db, **data.model_dump())
        except AppError as exc:
            print(f"Not created: {exc.code}", file=sys.stderr)
            return 1

    print(f"Created coop_admin user_id={user.user_id} ({user.mobile_no}), status active.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create_admin = commands.add_parser("create-admin", help="Create an active coop_admin account")
    create_admin.add_argument("--first-name", required=True)
    create_admin.add_argument("--last-name", required=True)
    create_admin.add_argument("--mobile-no", required=True, help="+639XXXXXXXXX")
    create_admin.add_argument("--municipality", required=True)
    create_admin.add_argument("--email")
    create_admin.set_defaults(handler=_create_admin)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
