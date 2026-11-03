"""Season rules (Section 4, Table 17) and Philippine 'today'."""

from datetime import UTC, date, datetime

import pytest

from app.core.seasons import cycle_season_year, philippine_today, season_of
from app.models.enums import CropSeason

WET, DRY = CropSeason.WET, CropSeason.DRY


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 5, 31), (DRY, 2025)),
        (date(2026, 6, 1), (WET, 2026)),
        (date(2026, 11, 30), (WET, 2026)),
        (date(2026, 12, 1), (DRY, 2026)),
        (date(2026, 12, 31), (DRY, 2026)),
        (date(2027, 1, 1), (DRY, 2026)),
        (date(2027, 5, 31), (DRY, 2026)),
    ],
)
def test_season_of_a_date(day: date, expected: tuple) -> None:
    assert season_of(day) == expected


@pytest.mark.parametrize(
    ("season", "sown", "expected"),
    [
        # A dry season from December 2026 to May 2027 is 2026, across December and January.
        (DRY, date(2026, 12, 15), 2026),
        (DRY, date(2027, 1, 5), 2026),
        (DRY, date(2027, 5, 31), 2026),
        (DRY, date(2027, 6, 1), 2027),
        (WET, date(2026, 6, 15), 2026),
        # Only a dry season moves back a year; a wet cycle keeps its sowing year.
        (WET, date(2027, 1, 5), 2027),
    ],
)
def test_cycle_season_year(season: CropSeason, sown: date, expected: int) -> None:
    assert cycle_season_year(season, sown) == expected


def test_philippine_today_is_ahead_of_utc_late_in_the_evening() -> None:
    # 16:30 UTC on Dec 31 is 00:30 on Jan 1 in the Philippines.
    assert philippine_today(datetime(2026, 12, 31, 16, 30, tzinfo=UTC)) == date(2027, 1, 1)
    assert philippine_today(datetime(2026, 12, 31, 15, 59, tzinfo=UTC)) == date(2026, 12, 31)
