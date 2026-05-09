from __future__ import annotations

from collections import Counter

import httpx
from pydantic import BaseModel

from memories_app.config import FiltersConfig
from memories_app.models import Memory


class AlbumSummary(BaseModel):
    id: str
    albumName: str
    assetCount: int


def fetch_albums_for_asset(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    asset_id: str,
) -> list[AlbumSummary]:
    url = f"{base_url.rstrip('/')}/api/albums"
    response = client.get(
        url,
        params={"assetId": asset_id},
        headers={"x-api-key": api_key, "accept": "application/json"},
        timeout=30.0,
    )
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, list):
        return []
    return [AlbumSummary.model_validate(item) for item in raw]


def resolve_memory_album_context(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    memory: Memory,
    filters: FiltersConfig,
) -> tuple[bool, str | None]:
    """Return (has_named_album for scoring, album display name for templates)."""
    blacklist = {name.casefold() for name in filters.album_blacklist}
    max_lookups = max(1, filters.max_album_lookups_per_memory)
    assets = memory.assets
    if not assets:
        return False, None

    indices = _evenly_spaced_indices(len(assets), max_lookups)
    name_votes: Counter[str] = Counter()

    for idx in indices:
        asset = assets[idx]
        try:
            albums = fetch_albums_for_asset(client, base_url, api_key, asset.id)
        except httpx.HTTPError:
            continue
        for album in albums:
            if album.assetCount > filters.album_dump_asset_threshold:
                continue
            if album.albumName.casefold() in blacklist:
                continue
            if not album.albumName.strip():
                continue
            name_votes[album.albumName.strip()] += 1

    if not name_votes:
        return False, None

    display_name = name_votes.most_common(1)[0][0]
    return True, display_name


def _evenly_spaced_indices(length: int, max_count: int) -> list[int]:
    if length <= max_count:
        return list(range(length))
    step = (length - 1) / (max_count - 1)
    raw = [min(length - 1, int(round(i * step))) for i in range(max_count)]
    return list(dict.fromkeys(raw))
