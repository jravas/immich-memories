from __future__ import annotations

import argparse
import json
import random
from datetime import date

import httpx
import reverse_geocoder
import structlog

from memories_app.config import load_config
from memories_app.db import connect, ensure_schema
from memories_app.immich_albums import resolve_memory_album_context
from memories_app.logging_utils import configure_logging
from memories_app.models import Asset, Memory
from memories_app.scoring import haversine_km, is_anniversary, score_memory, years_ago


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scout Immich memories and queue worthy ones.")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file")
    parser.add_argument("--date", default=date.today().isoformat(), help="Date in YYYY-MM-DD format")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates without writing to DB")
    parser.add_argument("--force", action="store_true", help="Queue all memories regardless of threshold")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    logger = structlog.get_logger("scout")
    config = load_config(args.config)
    today = date.fromisoformat(args.date)

    connection = connect(config.queue_db_path)
    ensure_schema(connection)

    with httpx.Client(timeout=30.0) as client:
        memories = fetch_memories(client, config.immich.base_url, config.immich.api_key, today.isoformat())

        queued = 0
        skipped = 0
        for memory in memories:
            if is_hidden(connection, memory.id):
                skipped += 1
                logger.info("scout.hidden", memory_id=memory.id)
                continue

            if not memory.assets:
                skipped += 1
                logger.info("scout.empty", memory_id=memory.id)
                continue

            has_named_album, album_display = resolve_memory_album_context(
                client,
                config.immich.base_url,
                config.immich.api_key,
                memory,
                config.filters,
            )
            score, _ = score_memory(
                memory,
                config.scout.home_gps,
                today,
                has_named_album=has_named_album,
            )
            if score < config.scout.threshold and not args.force:
                skipped += 1
                logger.info("scout.below_threshold", memory_id=memory.id, score=score)
                continue

            chosen_asset = pick_asset(memory)
            candidate_assets = get_candidate_assets(memory)
            city = detect_city(memory)
            title = make_title(memory.memoryAt, today, city)
            caption = make_caption(memory, city, album_display, today)

            logger.info(
                "scout.selected",
                memory_id=memory.id,
                asset_id=chosen_asset.id,
                candidate_count=len(candidate_assets),
                score=score,
                title=title,
                caption=caption,
                album=album_display,
            )
            if args.dry_run:
                continue

            upsert_queue_item(
                connection=connection,
                memory_id=memory.id,
                memory_date=memory.memoryAt,
                year=memory.year,
                asset_id=chosen_asset.id,
                candidate_assets=[asset.id for asset in candidate_assets],
                score=score,
                city=city,
                caption=caption,
            )
            queued += 1

    logger.info("scout.finished", total=len(memories), queued=queued, skipped=skipped, dry_run=args.dry_run)


def fetch_memories(client: httpx.Client, base_url: str, api_key: str, for_date: str) -> list[Memory]:
    url = f"{base_url.rstrip('/')}/api/memories"
    response = client.get(
        url,
        params={"for": for_date, "type": "on_this_day"},
        headers={"x-api-key": api_key, "accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    return [Memory.model_validate(item) for item in payload]


def pick_asset(memory: Memory) -> Asset:
    """Pick the single best asset for Phase 1 compatibility."""
    starred = [asset for asset in memory.assets if asset.isFavorite]
    if starred:
        return starred[0]

    with_faces = sorted(memory.assets, key=lambda asset: asset.face_count, reverse=True)
    if with_faces and with_faces[0].face_count > 0:
        return with_faces[0]

    centroid = gps_cluster_centroid(memory.assets)
    if centroid is not None:
        with_gps = [a for a in memory.assets if a.gps is not None]
        if with_gps:
            return min(with_gps, key=lambda a: _distance_to_centroid(centroid, a))

    with_gps = [asset for asset in memory.assets if asset.has_gps]
    if with_gps:
        return with_gps[0]

    return random.choice(memory.assets)


def get_candidate_assets(memory: Memory, max_candidates: int = 5) -> list[Asset]:
    """Get top candidate assets for Phase 2 LLM enrichment."""
    candidates = []
    
    # Priority 1: Starred photos
    starred = [asset for asset in memory.assets if asset.isFavorite]
    candidates.extend(starred[:max_candidates])
    
    if len(candidates) >= max_candidates:
        return candidates[:max_candidates]
    
    # Priority 2: Photos with faces (sorted by face count)
    with_faces = sorted(
        [asset for asset in memory.assets if asset.face_count > 0 and asset not in candidates],
        key=lambda asset: asset.face_count,
        reverse=True
    )
    candidates.extend(with_faces[:max_candidates - len(candidates)])
    
    if len(candidates) >= max_candidates:
        return candidates[:max_candidates]
    
    # Priority 3: Photos with GPS
    with_gps = [
        asset for asset in memory.assets 
        if asset.has_gps and asset not in candidates
    ]
    candidates.extend(with_gps[:max_candidates - len(candidates)])
    
    if len(candidates) >= max_candidates:
        return candidates[:max_candidates]
    
    # Priority 4: Random selection to fill remaining slots
    remaining = [
        asset for asset in memory.assets 
        if asset not in candidates
    ]
    candidates.extend(random.sample(remaining, min(max_candidates - len(candidates), len(remaining))))
    
    return candidates[:max_candidates]


def _distance_to_centroid(centroid: tuple[float, float], asset: Asset) -> float:
    gps = asset.gps
    if gps is None:
        return float("inf")
    return haversine_km(centroid, gps)


def gps_cluster_centroid(assets: list[Asset]) -> tuple[float, float] | None:
    points = [a.gps for a in assets if a.gps is not None]
    if not points:
        return None
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return lat, lon


def make_title(memory_at: str, today: date, city: str | None) -> str:
    years = years_ago(memory_at, today)
    if not city:
        return f"{years} years ago"
    return f"{years} years ago in {city}"


def make_caption(
    memory: Memory,
    city: str | None,
    album_display: str | None,
    today: date,
) -> str:
    anniversary_prefix = ""
    if is_anniversary(memory.memoryAt, today):
        anniversary_prefix = f"{years_ago(memory.memoryAt, today)} years ago today. "

    span_hours = memory_span_hours(memory)
    if city and span_hours >= 4:
        return f"{anniversary_prefix}You spent the day in {city}."
    if city and album_display:
        return f"{anniversary_prefix}{album_display} — {city}"
    if city:
        return f"{anniversary_prefix}You were in {city}."
    if album_display:
        return f"{anniversary_prefix}{album_display}."
    if memory.photo_count >= 10:
        return f"{anniversary_prefix}A day full of photos."
    return f"{anniversary_prefix}A moment worth remembering."


def detect_city(memory: Memory) -> str | None:
    for asset in memory.assets:
        if not asset.gps:
            continue
        lat, lon = asset.gps
        result = reverse_geocoder.search((lat, lon), mode=1)
        if not result:
            continue
        name = result[0].get("name")
        country = result[0].get("cc")
        if name and country:
            return f"{name}, {country}"
        if name:
            return str(name)

    for asset in memory.assets:
        ex_city = asset.exif_city
        if ex_city:
            return ex_city
    return None


def memory_span_hours(memory: Memory) -> float:
    timestamps = [asset.local_date for asset in memory.assets if asset.local_date is not None]
    if len(timestamps) < 2:
        return 0.0
    delta = max(timestamps) - min(timestamps)
    return delta.total_seconds() / 3600


def is_hidden(connection, memory_id: str) -> bool:
    row = connection.execute("SELECT 1 FROM hidden WHERE memory_id = ?", (memory_id,)).fetchone()
    return row is not None


def upsert_queue_item(
    connection,
    memory_id: str,
    memory_date: str,
    year: int,
    asset_id: str,
    candidate_assets: list[str] | None = None,
    score: int,
    city: str | None,
    caption: str,
) -> None:
    candidate_json = json.dumps(candidate_assets) if candidate_assets else None
    connection.execute(
        """
        INSERT INTO queue(memory_id, memory_date, year, asset_id, candidate_assets, score, city, caption, status)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(memory_id) DO UPDATE SET
          asset_id = excluded.asset_id,
          candidate_assets = excluded.candidate_assets,
          score = excluded.score,
          city = excluded.city,
          caption = excluded.caption
        """,
        (memory_id, memory_date, year, asset_id, candidate_json, score, city, caption),
    )
    connection.commit()


if __name__ == "__main__":
    main()
