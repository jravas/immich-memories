#!/usr/bin/env python3
"""
Phase 2 LLM Enricher - runs on Framework desktop, enhances queued memories with AI.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import ollama
import structlog
from pydantic import BaseModel, ValidationError

from memories_app.config import load_config
from memories_app.logging_utils import configure_logging

configure_logging()
logger = structlog.get_logger("enricher")


class EnrichmentResponse(BaseModel):
    """Structured response from vision model."""
    score: int  # 0-10 for memory worthiness
    best_index: int  # which photo is best (0-based)
    caption: str  # max 12 words, no exclamation marks


class Enricher:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.enricher_config = self.config.enricher
        self.nas_client = httpx.Client(
            base_url=self.enricher_config.nas_url,
            timeout=30.0,
            headers={"Authorization": f"Bearer {self.enricher_config.shared_secret}"}
        )
        self.immich_client = httpx.Client(
            base_url=self.config.immich.base_url,
            headers={"x-api-key": self.config.immich.api_key},
            timeout=30.0,
        )
        
    def get_pending_memories(self) -> list[dict[str, Any]]:
        """Fetch pending memories from NAS queue API."""
        try:
            response = self.nas_client.get("/queue/pending")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("enricher.http_error", status_code=e.response.status_code, error=str(e))
            return []
        except httpx.RequestError as e:
            logger.error("enricher.network_error", error=str(e))
            return []
        except Exception as e:
            logger.error("enricher.failed_to_fetch_pending", error=str(e))
            return []

    def fetch_candidate_thumbnails(self, memory_id: str, asset_ids: list[str]) -> list[bytes]:
        """Fetch thumbnails for top candidate photos."""
        thumbnails = []
        for asset_id in asset_ids[:5]:  # Max 5 candidates
            try:
                response = self.immich_client.get(
                    f"/api/assets/{asset_id}/thumbnail",
                    params={"size": "preview"},  # Larger than thumbnail for better AI analysis
                )
                response.raise_for_status()
                thumbnails.append(response.content)
            except httpx.HTTPStatusError as e:
                logger.warning("enricher.thumbnail_http_error", asset_id=asset_id, status_code=e.response.status_code, error=str(e))
            except httpx.RequestError as e:
                logger.warning("enricher.thumbnail_network_error", asset_id=asset_id, error=str(e))
            except Exception as e:
                logger.warning("enricher.failed_thumbnail", asset_id=asset_id, error=str(e))
        return thumbnails

    def call_vision_model(self, memory: dict[str, Any], thumbnails: list[bytes]) -> EnrichmentResponse | None:
        """Call Ollama vision model to score and select best photo."""
        if not thumbnails:
            return None

        # Prepare system prompt
        system_prompt = """You are scoring memory-worthiness for a personal photo app.
        
Rules:
- Score 0-10 for "worth surfacing as a memory" (10 = very special)
- Pick the single best photo index (0-based)
- Write one sentence caption (max 12 words, no exclamation marks)
- Use past tense, second person ("You were...")
- Only state what you can see, don't invent details
- Reply as JSON: {"score": int, "best_index": int, "caption": str}"""

        # Prepare user message with context
        user_msg_parts = [
            f"Here are {len(thumbnails)} photos from {memory['memory_date']}, {memory['year']} years ago.",
        ]
        
        if memory.get('city'):
            user_msg_parts.append(f"Location: {memory['city']}")
        
        user_msg_parts.extend([
            "Tasks:",
            "1) Score this day 0-10 for memory worthiness",
            "2) Pick the single best photo (return index)",
            "3) Write one sentence caption (max 12 words)",
            "Reply as JSON only.",
        ])

        # Prepare message with images
        message = {
            "role": "user",
            "content": [{"type": "text", "text": "\n".join(user_msg_parts)}],
        }
        
        # Add images to message
        for i, thumbnail in enumerate(thumbnails):
            message["content"].append({
                "type": "image_url",
                "image_url": f"data:image/jpeg;base64,{base64.b64encode(thumbnail).decode()}"
            })

        try:
            # Try primary model first
            response = ollama.chat(
                model=self.enricher_config.vision_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    message,
                ],
                format="json",
                options={"temperature": 0.1},  # Low temperature for consistent output
            )
            
            return EnrichmentResponse.model_validate_json(response.message.content)
            
        except ollama.ResponseError as e:
            logger.error("enricher.model_not_found", model=self.enricher_config.vision_model, error=str(e))
            # Model doesn't exist, try fallback immediately
        except (ollama.RequestError, ollama.OllamaError) as e:
            logger.warning("enricher.primary_model_failed", model=self.enricher_config.vision_model, error=str(e))
            # Network or server error, try fallback
        except ValidationError as e:
            logger.error("enricher.invalid_response", model=self.enricher_config.vision_model, error=str(e))
            # Invalid JSON response, try fallback
        except Exception as e:
            logger.error("enricher.unexpected_error", model=self.enricher_config.vision_model, error=str(e))
            # Unexpected error, try fallback
            
        # Try fallback model
        try:
            response = ollama.chat(
                model=self.enricher_config.fallback_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    message,
                ],
                format="json",
                options={"temperature": 0.1},
            )
            
            return EnrichmentResponse.model_validate_json(response.message.content)
            
        except ollama.ResponseError as e:
            logger.error("enricher.fallback_model_not_found", 
                       model=self.enricher_config.fallback_model, 
                       error=str(e))
            return None
        except (ollama.RequestError, ollama.OllamaError) as e:
            logger.error("enricher.fallback_model_failed", 
                       model=self.enricher_config.fallback_model,
                       error=str(e))
            return None
        except ValidationError as e:
            logger.error("enricher.fallback_invalid_response", 
                       model=self.enricher_config.fallback_model,
                       error=str(e))
            return None
        except Exception as e:
            logger.error("enricher.fallback_unexpected_error", 
                       model=self.enricher_config.fallback_model,
                       error=str(e))
            return None

    def update_memory(self, memory_id: str, enrichment: EnrichmentResponse, chosen_asset_id: str) -> bool:
        """Update memory on NAS with enrichment results."""
        try:
            response = self.nas_client.post(
                "/queue/update",
                json={
                    "memory_id": memory_id,
                    "asset_id": chosen_asset_id,
                    "caption": enrichment.caption,
                    "status": "enriched" if enrichment.score >= 5 else "skipped",
                }
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error("enricher.update_http_error", memory_id=memory_id, status_code=e.response.status_code, error=str(e))
            return False
        except httpx.RequestError as e:
            logger.error("enricher.update_network_error", memory_id=memory_id, error=str(e))
            return False
        except Exception as e:
            logger.error("enricher.failed_to_update", memory_id=memory_id, error=str(e))
            return False

    def process_memory(self, memory: dict[str, Any]) -> bool:
        """Process a single memory through LLM enrichment."""
        logger.info("enricher.processing_memory", memory_id=memory['memory_id'])
        
        # Get candidate thumbnails
        thumbnails = self.fetch_candidate_thumbnails(
            memory['memory_id'], 
            memory.get('candidate_asset_ids', [memory['asset_id']])
        )
        
        if not thumbnails:
            logger.warning("enricher.no_thumbnails", memory_id=memory['memory_id'])
            return False
        
        # Call vision model
        enrichment = self.call_vision_model(memory, thumbnails)
        if not enrichment:
            logger.warning("enricher.vision_failed", memory_id=memory['memory_id'])
            return False
        
        # Determine chosen asset
        candidate_assets = memory.get('candidate_asset_ids', [memory['asset_id']])
        if enrichment.best_index < len(candidate_assets):
            chosen_asset_id = candidate_assets[enrichment.best_index]
        else:
            chosen_asset_id = memory['asset_id']
        
        # Update memory
        success = self.update_memory(memory['memory_id'], enrichment, chosen_asset_id)
        if success:
            logger.info("enricher.memory_enriched", 
                        memory_id=memory['memory_id'],
                        score=enrichment.score,
                        caption=enrichment.caption)
        
        return success

    def run_once(self) -> None:
        """Run one enrichment cycle."""
        logger.info("enricher.cycle_start")
        
        pending_memories = self.get_pending_memories()
        if not pending_memories:
            logger.info("enricher.no_pending_memories")
            return
        
        logger.info("enricher.found_pending", count=len(pending_memories))
        
        for memory in pending_memories:
            try:
                self.process_memory(memory)
            except Exception as e:
                logger.error("enricher.processing_error", 
                           memory_id=memory.get('memory_id'), 
                           error=str(e))
    
    def run(self) -> None:
        """Run continuous enrichment loop."""
        logger.info("enricher.start", 
                   poll_interval=self.enricher_config.poll_interval_minutes)
        
        while True:
            try:
                self.run_once()
                time.sleep(self.enricher_config.poll_interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("enricher.shutdown")
                break
            except Exception as e:
                logger.error("enricher.unexpected_error", error=str(e))
                time.sleep(60)  # Wait 1 minute before retrying


def main():
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    enricher = Enricher(config_path)
    enricher.run()


if __name__ == "__main__":
    main()
