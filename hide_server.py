from __future__ import annotations

import os
from typing import Any, Dict

import structlog
from fastapi import FastAPI, Query, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

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
security = HTTPBearer()


def verify_enricher_auth(credentials: HTTPAuthorizationCredentials = Security(security)) -> bool:
    """Verify that the request has a valid enricher shared secret."""
    expected_secret = config.enricher.shared_secret
    if not expected_secret:
        logger.warning("hide_server.no_enricher_secret_configured")
        return False
    
    if credentials.credentials != expected_secret:
        logger.warning("hide_server.invalid_auth", token=credentials.credentials[:8] + "...")
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    
    return True


class QueueUpdateRequest(BaseModel):
    """Request model for updating queue entries."""
    memory_id: str
    asset_id: str
    caption: str
    status: str


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


@app.get("/queue/pending")
def get_pending_memories(authenticated: bool = Depends(verify_enricher_auth)) -> list[Dict[str, Any]]:
    """Get memories that are pending enrichment."""
    cursor = connection.execute(
        """
        SELECT 
            id, memory_id, memory_date, year, asset_id, candidate_assets, score, city, 
            caption, status, enriched_at, sent_at, created_at
        FROM queue 
        WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    )
    memories = []
    for row in cursor.fetchall():
        memory = dict(row)
        
        # Parse candidate assets from JSON, fallback to current asset_id
        if memory["candidate_assets"]:
            try:
                import json
                memory["candidate_asset_ids"] = json.loads(memory["candidate_assets"])
            except (json.JSONDecodeError, TypeError):
                memory["candidate_asset_ids"] = [memory["asset_id"]]
        else:
            memory["candidate_asset_ids"] = [memory["asset_id"]]
        
        # Remove the raw candidate_assets field for cleaner API
        del memory["candidate_assets"]
        memories.append(memory)
    
    logger.info("hide_server.pending_fetched", count=len(memories))
    return memories


@app.post("/queue/update")
def update_memory(request: QueueUpdateRequest, authenticated: bool = Depends(verify_enricher_auth)) -> dict[str, str]:
    """Update a memory with enrichment results."""
    try:
        connection.execute(
            """
            UPDATE queue
            SET asset_id = ?, caption = ?, status = ?, enriched_at = CURRENT_TIMESTAMP
            WHERE memory_id = ? AND status = 'pending'
            """,
            (request.asset_id, request.caption, request.status, request.memory_id),
        )
        connection.commit()
        
        if connection.total_changes == 0:
            raise HTTPException(status_code=404, detail="Memory not found or not pending")
        
        logger.info("hide_server.memory_updated", 
                   memory_id=request.memory_id,
                   asset_id=request.asset_id,
                   status=request.status)
        return {"status": "ok"}
        
    except Exception as e:
        logger.error("hide_server.update_failed", 
                    memory_id=request.memory_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail="Update failed")
