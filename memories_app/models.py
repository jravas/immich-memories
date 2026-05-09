from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Asset(BaseModel):
    id: str
    isFavorite: bool = False
    people: list[object] = Field(default_factory=list)
    exifInfo: dict[str, object] | None = None

    @property
    def face_count(self) -> int:
        return len(self.people)

    @property
    def has_gps(self) -> bool:
        exif = self.exifInfo or {}
        return exif.get("latitude") is not None and exif.get("longitude") is not None

    @property
    def gps(self) -> tuple[float, float] | None:
        exif = self.exifInfo or {}
        lat = exif.get("latitude")
        lon = exif.get("longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)

    @property
    def local_date(self) -> datetime | None:
        exif = self.exifInfo or {}
        date_taken = exif.get("dateTimeOriginal")
        if not isinstance(date_taken, str):
            return None
        try:
            return datetime.fromisoformat(date_taken.replace("Z", "+00:00"))
        except ValueError:
            return None


class Memory(BaseModel):
    id: str
    memoryAt: str
    isSaved: bool = False
    data: dict[str, int] = Field(default_factory=dict)
    assets: list[Asset] = Field(default_factory=list)

    @property
    def year(self) -> int:
        return int(self.data.get("year", 0))

    @property
    def photo_count(self) -> int:
        return len(self.assets)
