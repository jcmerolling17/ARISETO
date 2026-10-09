"""Domain constants shared by the models, schemas, and services."""

# The 11 Occidental Mindoro municipalities (users.municipality, barangay.municipality).
MUNICIPALITIES: tuple[str, ...] = (
    "Abra de Ilog",
    "Calintaan",
    "Looc",
    "Lubang",
    "Magsaysay",
    "Mamburao",
    "Paluan",
    "Rizal",
    "Sablayan",
    "San Jose",
    "Santa Cruz",
)

# Crops in scope (crop.crop_name).
CROPS_IN_SCOPE: tuple[str, ...] = ("rice", "corn", "onion")

# Rough bounding box of Occidental Mindoro, including Lubang Island (farm.latitude/longitude).
PROVINCE_BOUNDS = {"min_lat": 12.0, "max_lat": 14.0, "min_lon": 119.8, "max_lon": 121.4}

# A field's planting date must be within this many days of today, before or after.
PLANTING_WINDOW_DAYS = 730

MOBILE_PATTERN = r"^\+639[0-9]{9}$"
MIN_PASSWORD_LENGTH = 8


def sql_in_list(values: tuple[str, ...]) -> str:
    """Render values as a SQL IN list for CHECK constraints, e.g. ('a', 'b')."""
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"({quoted})"
