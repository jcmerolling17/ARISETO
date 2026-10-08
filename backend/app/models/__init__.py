"""Importing this package registers every table on Base.metadata."""

from app.models.barangay import Barangay
from app.models.crop import Crop, CropCycle, CropVariety
from app.models.crop_calendar import CalendarTemplateTask, CropActivity
from app.models.farm import Farm, FarmAssignment
from app.models.user import User
from app.models.weather import WeatherLog

__all__ = [
    "Barangay",
    "CalendarTemplateTask",
    "Crop",
    "CropActivity",
    "CropCycle",
    "CropVariety",
    "Farm",
    "FarmAssignment",
    "User",
    "WeatherLog",
]
