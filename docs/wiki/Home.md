# Immich Memories Wiki

`immich-memories` is a self-hosted memory notification system built around Immich and ntfy.

The project philosophy is simple: send fewer notifications, but make each one meaningful.

## Start here

- [Architecture](./Architecture.md)
- [Installation](./Installation.md)
- [Configuration](./Configuration.md)
- [Operations](./Operations.md)
- [Roadmap](./Roadmap.md)

## Project status

- **Phase 1 (MVP) is complete** — full heuristic pipeline, album integration, caption templates, supercronic scheduler, Docker stack.
- Queue and hide workflow use SQLite; hide by `memory_id` is idempotent.

## Core services

- `scout`: fetches memories, resolves albums (`/api/albums`), scores, picks a photo (GPS cluster), writes captions, queues work
- `sender`: sends queued memories to ntfy and marks delivery status
- `hide_server`: receives "Hide forever" actions and blocks specific memories from resurfacing
