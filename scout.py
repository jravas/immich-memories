from __future__ import annotations

import argparse
import random
from datetime import date

import httpx
import structlog

from memories_app.config import load_config
from memories_app.db import connect, ensure_schema
from memories_app.logging_utils import configure_logging
from memories_app.models import Memory
from memories_app.scoring import score_memory, years_ago


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
    memories = fetch_memories(config.immich.base_url, config.immich.api_key, today.isoformat())

    connection = connect(config.queue_db_path)
    ensure_schema(connection)

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

        score, distance = score_memory(memory, config.scout.home_gps, today)
        if score < config.scout.threshold and not args.force:
            skipped += 1
            logger.info("scout.below_threshold", memory_id=memory.id, score=score)
            continue

        chosen_asset = pick_asset(memory)
        title = make_title(memory.memoryAt, today)
        caption = make_caption(memory, distance)

        logger.info(
            "scout.selected",
            memory_id=memory.id,
            asset_id=chosen_asset.id,
            score=score,
            title=title,
            caption=caption,
        )
        if args.dry_run:
            continue

        upsert_queue_item(
            connection=connection,
            memory_id=memory.id,
            memory_date=memory.memoryAt,
            year=memory.year,
            asset_id=chosen_asset.id,
            score=score,
            caption=caption,
        )
        queued += 1

    logger.info("scout.finished", total=len(memories), queued=queued, skipped=skipped, dry_run=args.dry_run)


def fetch_memories(base_url: str, api_key: str, for_date: str) -> list[Memory]:
    url = f"{base_url.rstrip('/')}/api/memories"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            url,
            params={"for": for_date, "type": "on_this_day"},
            headers={"x-api-key": api_key, "accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    return [Memory.model_validate(item) for item in payload]


def pick_asset(memory: Memory):
    starred = [asset for asset in memory.assets if asset.isFavorite]
    if starred:
        return starred[0]

    with_faces = sorted(memory.assets, key=lambda asset: asset.face_count, reverse=True)
    if with_faces and with_faces[0].face_count > 0:
        return with_faces[0]

    with_gps = [asset for asset in memory.assets if asset.has_gps]
    if with_gps:
        return with_gps[0]

    return random.choice(memory.assets)


def make_title(memory_at: str, today: date) -> str:
    return f"{years_ago(memory_at, today)} years ago"


def make_caption(memory: Memory, distance_from_home_km: float) -> str:
    if distance_from_home_km > 50:
        return "You spent the day away from home."
    if memory.photo_count >= 10:
        return "A day full of photos."
    return "A moment worth remembering."


def is_hidden(connection, memory_id: str) -> bool:
    row = connection.execute("SELECT 1 FROM hidden WHERE memory_id = ?", (memory_id,)).fetchone()
    return row is not None


def upsert_queue_item(
    connection,
    memory_id: str,
    memory_date: str,
    year: int,
    asset_id: str,
    score: int,
    caption: str,
) -> None:
    connection.execute(
        """
        INSERT INTO queue(memory_id, memory_date, year, asset_id, score, caption, status)
        VALUES(?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(memory_id) DO UPDATE SET
          asset_id = excluded.asset_id,
          score = excluded.score,
          caption = excluded.caption
        """,
        (memory_id, memory_date, year, asset_id, score, caption),
    )
    connection.commit()


if __name__ == "__main__":
    main()
