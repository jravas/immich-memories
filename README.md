# Immich Memories

Phase 1 MVP for a self-hosted Immich memory notifier.

## Included components

- `scout.py`: fetches Immich "on this day" memories, scores them, and queues high-value memories
- `sender.py`: drains queued memories and sends ntfy notifications
- `hide_server.py`: provides a `POST /hide?memory_id=...` endpoint for the "Hide forever" action

## Quick start

1. Set `IMMICH_API_KEY` in your shell environment.
2. Review `config.yaml`.
3. Run a dry run:

```bash
python scout.py --config config.yaml --dry-run
```

4. Start services with Docker Compose:

```bash
docker compose up --build
```
