from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ImmichConfig(BaseModel):
    base_url: str
    api_key: str


class NtfyConfig(BaseModel):
    base_url: str
    topic: str


class ScoutConfig(BaseModel):
    threshold: int = 5
    home_gps: tuple[float, float] = (0.0, 0.0)
    hide_action_url: str = "http://hide-server:8080/hide"


class SchedulerConfig(BaseModel):
    """Cron expressions for supercronic (minute hour dom mon dow)."""

    scout_cron: str = "0 20 * * *"
    sender_cron: str = "*/10 * * * *"


class FiltersConfig(BaseModel):
    """Album-based filtering for scoring and captions (Phase 1)."""

    album_blacklist: list[str] = Field(
        default_factory=lambda: [
            "Screenshots",
            "Documents",
            "Work",
            "WhatsApp",
        ]
    )
    album_dump_asset_threshold: int = 500
    max_album_lookups_per_memory: int = 12


class EnricherConfig(BaseModel):
    """Phase 2 LLM enrichment settings."""
    
    enabled: bool = True
    poll_interval_minutes: int = 30
    nas_url: str = "http://hide-server:8080"
    vision_model: str = "qwen2.5vl:7b"
    fallback_model: str = "moondream2"
    timeout_seconds: int = 60


class AppConfig(BaseModel):
    immich: ImmichConfig
    ntfy: NtfyConfig
    scout: ScoutConfig = Field(default_factory=ScoutConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    enricher: EnricherConfig = Field(default_factory=EnricherConfig)
    queue_db_path: str = "data/queue.sqlite"


def _resolve_env(value: str) -> str:
    if not value.startswith("${") or not value.endswith("}"):
        return value
    env_name = value[2:-1]
    return os.environ.get(env_name, "")


def load_config(path: str) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if "immich" in raw and "api_key" in raw["immich"]:
        raw["immich"]["api_key"] = _resolve_env(raw["immich"]["api_key"])
    return AppConfig.model_validate(raw)
