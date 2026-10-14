"""Command line tasks.

Create the first cooperative administrator (run from backend/ with the venv active):

    python -m app.cli create-admin --first-name Maria --last-name Santos \
        --mobile-no +639171234567 --municipality "San Jose"

The password is asked for twice and never echoed.

Load the barangays and crop varieties in app/seeds/ (safe to run again):

    python -m app.cli seed

Fetch OpenWeatherMap once for every farm, or for one farm (needs OPENWEATHERMAP_API_KEY):

    python -m app.cli fetch-weather [--farm-id 3]

Run the weather scheduler as its own process: every farm now, then every 3 hours, until
Ctrl+C. Never start it inside the API server.

    python -m app.cli weather-scheduler
"""

import argparse
import getpass
import logging
import sys

from pydantic import ValidationError

from app.core.errors import AppError
from app.db.session import SessionLocal
from app.schemas.admin import AdminCreate
from app.services import auth_service, seed_service, weather_fetch_service, weather_scheduler

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


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


def _fetch_weather(args: argparse.Namespace) -> int:
    # Failed farms are logged by reason only; the key is never printed or logged.
    logging.basicConfig(level=logging.WARNING, format=LOG_FORMAT)
    farm_ids = None if args.farm_id is None else [args.farm_id]
    summary = weather_fetch_service.fetch_farms(farm_ids)

    if args.farm_id is not None and not summary.succeeded and not summary.failed:
        print(f"Farm {args.farm_id} not found.", file=sys.stderr)
        return 1
    if "missing_key" in summary.failed.values():
        print("OPENWEATHERMAP_API_KEY is not set in .env; nothing was fetched.", file=sys.stderr)
    print(
        f"Weather fetched: {len(summary.succeeded)} farms succeeded, {len(summary.failed)} failed."
    )
    return 1 if summary.failed else 0


def _weather_scheduler(_args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    # One line per run from app.weather; APScheduler's own per-job lines only on problems.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    weather_scheduler.run_forever()
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

    fetch_weather = commands.add_parser(
        "fetch-weather", help="Fetch OpenWeatherMap once and save it in weather_log"
    )
    fetch_weather.add_argument("--farm-id", type=int, help="Only this farm (default: all)")
    fetch_weather.set_defaults(handler=_fetch_weather)

    scheduler = commands.add_parser(
        "weather-scheduler", help="Fetch every farm now and then every 3 hours (own process)"
    )
    scheduler.set_defaults(handler=_weather_scheduler)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
