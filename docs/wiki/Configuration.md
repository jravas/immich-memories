# Configuration

Main runtime configuration lives in `config.yaml`.

## Example

```yaml
immich:
  base_url: "http://immich-server:2283"
  api_key: "${IMMICH_API_KEY}"

ntfy:
  base_url: "http://ntfy"
  topic: "memories"

scout:
  threshold: 5
  home_gps: [45.8150, 15.9819]
  hide_action_url: "http://hide-server:8080/hide"

filters:
  album_blacklist:
    - "Screenshots"
    - "Documents"
    - "Work"
    - "WhatsApp"
  album_dump_asset_threshold: 500
  max_album_lookups_per_memory: 12

scheduler:
  scout_cron: "0 20 * * *"
  sender_cron: "*/10 * * * *"

queue_db_path: "data/queue.sqlite"
```

## Fields

- `immich.base_url`: base URL for Immich API
- `immich.api_key`: API key value or `${ENV_VAR}` reference
- `ntfy.base_url`: ntfy server URL
- `ntfy.topic`: target ntfy topic
- `scout.threshold`: minimum score required to queue memory
- `scout.home_gps`: `[lat, lon]` reference point for distance scoring
- `scout.hide_action_url`: endpoint called by notification hide action
- `filters.album_blacklist`: album names (case-insensitive) ignored for scoring and captions
- `filters.album_dump_asset_threshold`: albums with more assets than this are treated as dumps (ignored for album context)
- `filters.max_album_lookups_per_memory`: max `GET /api/albums?assetId=` calls per memory (evenly sampled assets)
- `scheduler.scout_cron`: cron expression for daily (or custom) scout runs (default 20:00 UTC in container)
- `scheduler.sender_cron`: cron expression for how often to drain the queue to ntfy
- `queue_db_path`: SQLite file path

Cron uses five fields: minute, hour, day-of-month, month, day-of-week. The `scheduler` service defaults to `TZ=UTC`; set `TZ` in your environment (for example `Europe/Zagreb`) so `0 20 * * *` matches local 20:00.

## Runtime flags

### `scout.py`

- `--config`: config path (default `config.yaml`)
- `--date`: evaluate a specific date in `YYYY-MM-DD`
- `--dry-run`: print selected memories without DB writes
- `--force`: queue memories even below threshold

### `sender.py`

- `--config`: config path (default `config.yaml`)
- `--limit`: max rows sent per execution (default `20`)
