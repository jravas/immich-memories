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


class AppConfig(BaseModel):
    immich: ImmichConfig
    ntfy: NtfyConfig
    scout: ScoutConfig = Field(default_factory=ScoutConfig)
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
