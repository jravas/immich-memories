from __future__ import annotations

import os

import structlog
from fastapi import FastAPI, Query

from memories_app.config import load_config
from memories_app.db import connect, ensure_schema
from memories_app.logging_utils import configure_logging

configure_logging()
logger = structlog.get_logger("hide_server")
config_path = os.environ.get("CONFIG_PATH", "config.yaml")
config = load_config(config_path)
connection = connect(config.queue_db_path)
ensure_schema(connection)

app = FastAPI()


@app.post("/hide")
def hide(memory_id: str = Query(..., min_length=1)) -> dict[str, str]:
    connection.execute(
        "INSERT OR IGNORE INTO hidden(memory_id) VALUES (?)",
        (memory_id,),
    )
    connection.execute(
        """
        UPDATE queue
        SET status = 'skipped'
        WHERE memory_id = ? AND status IN ('pending', 'enriched', 'failed')
        """,
        (memory_id,),
    )
    connection.commit()
    logger.info("hide_server.hidden", memory_id=memory_id)
    return {"status": "ok"}
