# Roadmap

This roadmap tracks execution priorities from `plan.md`.

## Phase 1 (MVP) — complete

- [x] `scout.py` — Immich fetch, scoring, album-aware captions, GPS cluster pick, queue write
- [x] `sender.py` — ntfy delivery
- [x] `hide_server.py` — idempotent hide by `memory_id`
- [x] SQLite schema bootstrap and status transitions
- [x] Containerization (`Dockerfile`, `docker-compose.yml`, `.dockerignore`, hide healthcheck)
- [x] Reverse geocoding + EXIF city fallback for titles/captions
- [x] Template selection (city, day-span, album name, volume, anniversary prefix)
- [x] Album scoring via `GET /api/albums?assetId=` + blacklist / dump-album threshold
- [x] Scheduler (supercronic; cron from `config.yaml`)

## Phase 2 (LLM enricher) — complete

- [x] `enricher.py` worker on Framework desktop
- [x] Queue API endpoints for pending/update
- [x] Ollama vision model integration (`qwen2.5vl:7b`, fallback `moondream2`)
- [x] Strict JSON output parsing and heuristic fallback

## Phase 3 (optional polish)

- [ ] Weekly digest mode
- [ ] Multi-year merge/spread strategy
- [ ] Sentiment/album filtering improvements
- [ ] Threshold self-tuning
