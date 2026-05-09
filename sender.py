from __future__ import annotations

import argparse
import urllib.parse
from datetime import datetime, timezone

import httpx
import structlog

from memories_app.config import load_config
from memories_app.db import connect, ensure_schema
from memories_app.logging_utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send queued memories to ntfy.")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file")
    parser.add_argument("--limit", type=int, default=20, help="Maximum queue rows to send")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    logger = structlog.get_logger("sender")

    config = load_config(args.config)
    connection = connect(config.queue_db_path)
    ensure_schema(connection)

    rows = connection.execute(
        """
        SELECT id, memory_id, memory_date, year, asset_id, caption, status
        FROM queue
        WHERE status IN ('pending', 'enriched')
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()

    if not rows:
        logger.info("sender.empty")
        return

    with httpx.Client(timeout=30.0) as client:
        for row in rows:
            notification_url = f"{config.ntfy.base_url.rstrip('/')}/{config.ntfy.topic}"
            thumbnail_url = (
                f"{config.immich.base_url.rstrip('/')}/api/assets/{row['asset_id']}/thumbnail?size=thumbnail"
            )
            hide_url = (
                f"{config.scout.hide_action_url}?memory_id="
                f"{urllib.parse.quote(row['memory_id'], safe='')}"
            )
            headers = {
                "Title": f"{_years_ago(row['memory_date'])} years ago",
                "Tags": "frame_with_picture",
                "Priority": "default",
                "Click": f"immich://asset/{row['asset_id']}",
                "Attach": thumbnail_url,
                "Actions": f"view, Hide forever, {hide_url}, method=POST",
            }

            try:
                response = client.post(notification_url, content=row["caption"], headers=headers)
                response.raise_for_status()
                mark_as_sent(connection, queue_id=row["id"])
                logger.info("sender.sent", queue_id=row["id"], memory_id=row["memory_id"])
            except httpx.HTTPError as error:
                mark_as_failed(connection, queue_id=row["id"])
                logger.error(
                    "sender.failed",
                    queue_id=row["id"],
                    memory_id=row["memory_id"],
                    error=str(error),
                )


def _years_ago(memory_date: str) -> int:
    year = datetime.fromisoformat(memory_date).year
    return datetime.now(tz=timezone.utc).year - year


def mark_as_sent(connection, queue_id: int) -> None:
    connection.execute(
        "UPDATE queue SET status = 'sent', sent_at = CURRENT_TIMESTAMP WHERE id = ?",
        (queue_id,),
    )
    connection.commit()


def mark_as_failed(connection, queue_id: int) -> None:
    connection.execute("UPDATE queue SET status = 'failed' WHERE id = ?", (queue_id,))
    connection.commit()


if __name__ == "__main__":
    main()
