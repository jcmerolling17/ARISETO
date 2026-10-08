from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    SmallInteger,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WeatherLog(Base):
    """WEATHER_LOG: cached OpenWeatherMap readings, fetched by the backend scheduler only."""

    __tablename__ = "weather_log"
    __table_args__ = (
        CheckConstraint("humidity_pct BETWEEN 0 AND 100", name="humidity_pct_range"),
        CheckConstraint(
            "precip_probability_pct BETWEEN 0 AND 100", name="precip_probability_pct_range"
        ),
    )

    weather_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farm.farm_id"))
    forecast_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temp_c: Mapped[Decimal | None] = mapped_column(Numeric)
    feels_like_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    humidity_pct: Mapped[int | None] = mapped_column(SmallInteger)
    rain_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    precip_probability_pct: Mapped[int | None] = mapped_column(SmallInteger)
    wind_speed_mps: Mapped[Decimal | None] = mapped_column(Numeric)
    condition_code: Mapped[int] = mapped_column(SmallInteger)
    is_forecast: Mapped[bool] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
