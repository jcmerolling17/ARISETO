"""The US National Weather Service heat index (Rothfusz regression with its adjustments),
checked against the NWS heat index chart, which lists whole °F values."""

import math

import pytest

from app.services.alert_service import heat_index_c


def _hi_f(temp_f: float, humidity: float) -> float:
    """heat_index_c, in and out of °F like the NWS chart."""
    return heat_index_c((temp_f - 32) * 5 / 9, humidity) * 9 / 5 + 32


@pytest.mark.parametrize(
    ("temp_f", "humidity", "chart_f"),
    [
        (80, 40, 80),
        (90, 70, 106),
        (96, 65, 121),
        (100, 50, 118),
        (104, 40, 119),
        (86, 90, 105),
        (110, 40, 136),
    ],
)
def test_matches_the_nws_chart(temp_f: float, humidity: float, chart_f: int) -> None:
    assert round(_hi_f(temp_f, humidity)) == chart_f


def _rothfusz(t: float, rh: float) -> float:
    return (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )


def test_below_80_f_uses_the_simple_formula() -> None:
    # 0.5 × (70 + 61 + (70 − 68) × 1.2 + 50 × 0.094) = 69.05 °F
    assert _hi_f(70, 50) == pytest.approx(69.05)


def test_low_humidity_adjustment() -> None:
    adjustment = ((13 - 10) / 4) * math.sqrt((17 - abs(100 - 95)) / 17)
    assert _hi_f(100, 10) == pytest.approx(_rothfusz(100, 10) - adjustment)


def test_high_humidity_adjustment() -> None:
    adjustment = ((95 - 85) / 10) * ((87 - 82) / 5)
    assert _hi_f(82, 95) == pytest.approx(_rothfusz(82, 95) + adjustment)


def test_no_adjustment_outside_their_ranges() -> None:
    assert _hi_f(90, 13) == pytest.approx(_rothfusz(90, 13))
    assert _hi_f(88, 95) == pytest.approx(_rothfusz(88, 95))


def test_returns_celsius() -> None:
    # 90 °F (32.2 °C) at 70 %: about 106 °F, which is about 41 °C.
    assert heat_index_c(32.2222, 70) == pytest.approx(41.1, abs=0.1)
