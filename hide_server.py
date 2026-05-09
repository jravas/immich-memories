from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
import structlog

from memories_app.config import load_config
from memories_app.db import connect, ensure_schema
from memories_app.logging_utils import configure_logging

configure_logging()
logger = structlog.get_logger("hide_server")
config = load_config("config.yaml")
connection = connect(config.queue_db_path)
ensure_schema(connection)

app = FastAPI()


@app.post("/hide")
def hide(memory_id: str = Query(..., min_length=1)) -> dict[str, str]:
    row = connection.execute("SELECT memory_id FROM queue WHERE memory_id = ?", (memory_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown memory_id")

    connection.execute(
        "INSERT OR IGNORE INTO hidden(memory_id) VALUES (?)",
        (memory_id,),
    )
    connection.execute(
        "UPDATE queue SET status = 'skipped' WHERE memory_id = ? AND status != 'sent'",
        (memory_id,),
    )
    connection.commit()
    logger.info("hide_server.hidden", memory_id=memory_id)
    return {"status": "ok"}
