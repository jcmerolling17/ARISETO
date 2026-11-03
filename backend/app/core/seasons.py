"""Philippine dates and cropping seasons (Section 4, Table 17).

The wet season runs June to November and the dry season December to May. A season is named
by the year it starts, so the dry season from December 2026 to May 2027 is dry 2026.
"""

from datetime import UTC, date, datetime, timedelta, timezone

from app.models.enums import CropSeason

# Philippine time is UTC+8 all year (no daylight saving), so a fixed offset is exact.
PHILIPPINE_TIME = timezone(timedelta(hours=8), "PHT")


def philippine_today(now: datetime | None = None) -> date:
    """Today's date in the Philippines, whatever the server's time zone."""
    return (now or datetime.now(UTC)).astimezone(PHILIPPINE_TIME).date()


def season_of(day: date) -> tuple[CropSeason, int]:
    """The season and season_year a date falls in."""
    if 6 <= day.month <= 11:
        return CropSeason.WET, day.year
    if day.month == 12:
        return CropSeason.DRY, day.year
    return CropSeason.DRY, day.year - 1


def cycle_season_year(season: CropSeason, planting_date: date) -> int:
    """A crop cycle's season_year: the planting_date's year, minus 1 when the season is dry
    and the date falls in January to May."""
    if season == CropSeason.DRY and planting_date.month <= 5:
        return planting_date.year - 1
    return planting_date.year
