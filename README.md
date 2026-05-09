# Immich Memories

Phase 1 (MVP) is feature-complete: scout (scoring, albums, templates, GPS cluster pick), sender, hide server, SQLite queue, supercronic scheduler, and Docker Compose.

## Wiki

- [Home](docs/wiki/Home.md)
- [Architecture](docs/wiki/Architecture.md)
- [Installation](docs/wiki/Installation.md)
- [Configuration](docs/wiki/Configuration.md)
- [Operations](docs/wiki/Operations.md)
- [Roadmap](docs/wiki/Roadmap.md)

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

4. Start services with Docker Compose (scheduler + hide server by default):

```bash
docker compose up --build
```

The `scheduler` service runs `scout` and `sender` on the cron schedules in `config.yaml` (`scheduler.scout_cron`, `scheduler.sender_cron`) via [supercronic](https://github.com/aptible/supercronic).

Run `scout` or `sender` once manually:

```bash
docker compose --profile manual run --rm scout
docker compose --profile manual run --rm sender
```
