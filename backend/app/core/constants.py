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

MOBILE_PATTERN = r"^\+639[0-9]{9}$"
MIN_PASSWORD_LENGTH = 8


def sql_in_list(values: tuple[str, ...]) -> str:
    """Render values as a SQL IN list for CHECK constraints, e.g. ('a', 'b')."""
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"({quoted})"
