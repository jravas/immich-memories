from __future__ import annotations

import math
from datetime import date

from memories_app.models import Memory


def haversine_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def years_ago(memory_date: str, today: date) -> int:
    return max(today.year - date.fromisoformat(memory_date).year, 0)


def is_anniversary(memory_date: str, today: date, years: tuple[int, ...] = (1, 2, 5, 10, 20)) -> bool:
    return years_ago(memory_date, today) in years


def score_memory(memory: Memory, home_gps: tuple[float, float], today: date) -> tuple[int, float]:
    score = 0
    n = memory.photo_count
    if n >= 20:
        score += 3
    elif n >= 10:
        score += 2
    elif n >= 5:
        score += 1

    has_starred_photo = any(asset.isFavorite for asset in memory.assets)
    if has_starred_photo:
        score += 3

    if memory.isSaved:
        score += 3

    longest_span_hours = _span_hours(memory)
    if longest_span_hours >= 4:
        score += 1

    max_faces = max((asset.face_count for asset in memory.assets), default=0)
    if max_faces >= 3:
        score += 2

    max_distance = _distance_from_home(memory, home_gps)
    if max_distance > 50:
        score += 3

    if is_anniversary(memory.memoryAt, today):
        score += 99

    return score, max_distance


def _distance_from_home(memory: Memory, home_gps: tuple[float, float]) -> float:
    distances = []
    for asset in memory.assets:
        gps = asset.gps
        if gps is None:
            continue
        distances.append(haversine_km(home_gps, gps))
    return max(distances, default=0.0)


def _span_hours(memory: Memory) -> float:
    dates = [asset.local_date for asset in memory.assets if asset.local_date is not None]
    if len(dates) < 2:
        return 0.0
    delta = max(dates) - min(dates)
    return delta.total_seconds() / 3600
