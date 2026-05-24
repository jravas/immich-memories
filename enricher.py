#!/usr/bin/env python3
"""
Phase 2 LLM Enricher - runs on Framework desktop, enhances queued memories with AI.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
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

    score: int       # 0-10 for memory worthiness
    best_index: int  # which photo is best (0-based)
    caption: str     # max 12 words, no exclamation marks


@dataclass
class CycleMetrics:
    attempted: int = 0
    enriched: int = 0
    skipped: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)

    def record(self, outcome: str, latency_s: float) -> None:
        self.attempted += 1
        self.latencies.append(latency_s)
        if outcome == "enriched":
            self.enriched += 1
        elif outcome == "skipped":
            self.skipped += 1
        else:
            self.failed += 1

    def log(self) -> None:
        if not self.attempted:
            return
        avg_latency = sum(self.latencies) / len(self.latencies)
        success_rate = (self.enriched + self.skipped) / self.attempted
        logger.info(
            "enricher.cycle_metrics",
            attempted=self.attempted,
            enriched=self.enriched,
            skipped=self.skipped,
            failed=self.failed,
            success_rate=round(success_rate, 2),
            avg_latency_s=round(avg_latency, 1),
        )


class Enricher:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.enricher_config = self.config.enricher
        self.nas_client = httpx.Client(
            base_url=self.enricher_config.nas_url,
            timeout=30.0,
            headers={"Authorization": f"Bearer {self.enricher_config.shared_secret}"},
        )
        self.immich_client = httpx.Client(
            base_url=self.config.immich.base_url,
            headers={"x-api-key": self.config.immich.api_key},
            timeout=30.0,
        )
        self.ollama_client = ollama.Client(
            host=self.enricher_config.ollama_url,
            timeout=self.enricher_config.timeout_seconds,
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

    def fetch_candidate_thumbnails(self, asset_ids: list[str]) -> list[bytes]:
        """Fetch preview thumbnails for top candidate photos."""
        thumbnails = []
        for asset_id in asset_ids[:5]:
            try:
                response = self.immich_client.get(
                    f"/api/assets/{asset_id}/thumbnail",
                    params={"size": "preview"},
                )
                response.raise_for_status()
                thumbnails.append(response.content)
            except httpx.HTTPStatusError as e:
                logger.warning("enricher.thumbnail_http_error", asset_id=asset_id, status_code=e.response.status_code)
            except httpx.RequestError as e:
                logger.warning("enricher.thumbnail_network_error", asset_id=asset_id, error=str(e))
            except Exception as e:
                logger.warning("enricher.failed_thumbnail", asset_id=asset_id, error=str(e))
        return thumbnails

    def _build_ollama_message(self, memory: dict[str, Any], thumbnails: list[bytes]) -> dict[str, Any]:
        years_elapsed = datetime.now(timezone.utc).year - memory["year"]
        parts = [
            f"Here are {len(thumbnails)} photos from {memory['memory_date']}, {years_elapsed} years ago.",
        ]
        if memory.get("city"):
            parts.append(f"Location: {memory['city']}")
        parts.extend([
            "Tasks:",
            "1) Score this day 0-10 for memory worthiness",
            "2) Pick the single best photo (return index)",
            "3) Write one sentence caption (max 12 words)",
            "Reply as JSON only.",
        ])
        return {
            "role": "user",
            "content": "\n".join(parts),
            "images": [base64.b64encode(t).decode() for t in thumbnails],
        }

    def _chat(self, model: str, system_prompt: str, user_message: dict[str, Any]) -> EnrichmentResponse | None:
        """Call a single Ollama model and return parsed response, or None on failure."""
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    user_message,
                ],
                format="json",
                options={"temperature": 0.1},
            )
            return EnrichmentResponse.model_validate_json(response.message.content)
        except ollama.ResponseError as e:
            logger.error("enricher.model_not_found", model=model, error=str(e))
        except (ollama.RequestError, ollama.OllamaError) as e:
            logger.warning("enricher.model_failed", model=model, error=str(e))
        except ValidationError as e:
            logger.error("enricher.invalid_response", model=model, error=str(e))
        except Exception as e:
            logger.error("enricher.unexpected_error", model=model, error=str(e))
        return None

    def call_vision_model(self, memory: dict[str, Any], thumbnails: list[bytes]) -> EnrichmentResponse | None:
        """Call Ollama vision model, falling back to secondary model on failure."""
        if not thumbnails:
            return None

        system_prompt = (
            "You are scoring memory-worthiness for a personal photo app.\n\n"
            "Rules:\n"
            "- Score 0-10 for \"worth surfacing as a memory\" (10 = very special)\n"
            "- Pick the single best photo index (0-based)\n"
            "- Write one sentence caption (max 12 words, no exclamation marks)\n"
            "- Use past tense, second person (\"You were...\")\n"
            "- Only state what you can see, don't invent details\n"
            "- Reply as JSON: {\"score\": int, \"best_index\": int, \"caption\": str}"
        )
        user_message = self._build_ollama_message(memory, thumbnails)

        result = self._chat(self.enricher_config.vision_model, system_prompt, user_message)
        if result is not None:
            return result

        logger.info("enricher.trying_fallback", fallback_model=self.enricher_config.fallback_model)
        return self._chat(self.enricher_config.fallback_model, system_prompt, user_message)

    def update_memory(self, memory_id: str, enrichment: EnrichmentResponse, chosen_asset_id: str) -> bool:
        """Push enrichment results back to NAS queue API."""
        try:
            response = self.nas_client.post(
                "/queue/update",
                json={
                    "memory_id": memory_id,
                    "asset_id": chosen_asset_id,
                    "caption": enrichment.caption,
                    "status": "enriched" if enrichment.score >= 5 else "skipped",
                },
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

    def process_memory(self, memory: dict[str, Any], metrics: CycleMetrics) -> None:
        """Process a single memory through LLM enrichment, updating metrics in-place."""
        memory_id = memory["memory_id"]
        logger.info("enricher.processing_memory", memory_id=memory_id)
        t0 = time.monotonic()

        candidate_ids: list[str] = memory.get("candidate_asset_ids") or [memory["asset_id"]]
        thumbnails = self.fetch_candidate_thumbnails(candidate_ids)

        if not thumbnails:
            logger.warning("enricher.no_thumbnails", memory_id=memory_id)
            metrics.record("failed", time.monotonic() - t0)
            return

        enrichment = self.call_vision_model(memory, thumbnails)
        if not enrichment:
            logger.warning("enricher.vision_failed", memory_id=memory_id)
            metrics.record("failed", time.monotonic() - t0)
            return

        chosen_asset_id = (
            candidate_ids[enrichment.best_index]
            if enrichment.best_index < len(candidate_ids)
            else memory["asset_id"]
        )

        outcome = "enriched" if enrichment.score >= 5 else "skipped"
        if self.update_memory(memory_id, enrichment, chosen_asset_id):
            logger.info(
                "enricher.memory_processed",
                memory_id=memory_id,
                score=enrichment.score,
                outcome=outcome,
                caption=enrichment.caption,
            )
            metrics.record(outcome, time.monotonic() - t0)
        else:
            metrics.record("failed", time.monotonic() - t0)

    def run_once(self) -> None:
        """Run one enrichment cycle."""
        logger.info("enricher.cycle_start")

        pending = self.get_pending_memories()
        if not pending:
            logger.info("enricher.no_pending_memories")
            return

        logger.info("enricher.found_pending", count=len(pending))
        metrics = CycleMetrics()

        for memory in pending:
            try:
                self.process_memory(memory, metrics)
            except Exception as e:
                logger.error("enricher.processing_error", memory_id=memory.get("memory_id"), error=str(e))
                metrics.record("failed", 0.0)

        metrics.log()

    def run(self) -> None:
        """Run continuous enrichment loop."""
        logger.info("enricher.start", poll_interval=self.enricher_config.poll_interval_minutes)

        while True:
            try:
                self.run_once()
                time.sleep(self.enricher_config.poll_interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("enricher.shutdown")
                break
            except Exception as e:
                logger.error("enricher.unexpected_error", error=str(e))
                time.sleep(60)


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    Enricher(config_path).run()


if __name__ == "__main__":
    main()
