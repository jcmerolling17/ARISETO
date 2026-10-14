"""Command line tasks.

Create the first cooperative administrator (run from backend/ with the venv active):

    python -m app.cli create-admin --first-name Maria --last-name Santos \
        --mobile-no +639171234567 --municipality "San Jose"

The password is asked for twice and never echoed.

Load the barangays and crop varieties in app/seeds/ (safe to run again):

    python -m app.cli seed
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app.core.errors import AppError
from app.db.session import SessionLocal
from app.schemas.admin import AdminCreate
from app.services import auth_service, seed_service


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


def _seed(_args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            results = seed_service.seed_all(db)
        except seed_service.SeedFileError as exc:
            print(f"Nothing loaded: {exc}", file=sys.stderr)
            return 1
        barangays = seed_service.barangay_counts(db)
        varieties = seed_service.variety_counts(db)

    for name, result in results.items():
        print(f"{name}: {result.added} added, {result.updated} updated")
    print(f"Barangays per municipality ({sum(barangays.values())} in total):")
    for municipality, count in barangays.items():
        print(f"  {municipality}: {count}")
    print(f"Varieties per crop ({sum(varieties.values())} in total):")
    for crop, count in varieties.items():
        print(f"  {crop}: {count}")
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

    seed = commands.add_parser("seed", help="Load the barangays and crop varieties")
    seed.set_defaults(handler=_seed)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
