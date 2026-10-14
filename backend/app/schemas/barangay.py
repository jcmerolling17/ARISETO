from pydantic import BaseModel, ConfigDict


class BarangayOut(BaseModel):
    """GET /barangays item (Section 6). Coordinates are JSON numbers."""

    model_config = ConfigDict(from_attributes=True)

    barangay_id: int
    barangay_name: str
    center_latitude: float
    center_longitude: float
