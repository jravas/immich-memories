# Operations

## Normal flow

1. With Docker Compose, the `scheduler` container runs `scout.py` and `sender.py` on the cron schedules in `config.yaml` (`scheduler.scout_cron`, `scheduler.sender_cron`).
2. Keep `hide_server` reachable at the URL configured in `scout.hide_action_url` so notification actions work.
3. For bare-metal installs, use system cron or another scheduler to run the same commands.

## Manual commands

Dry run scout:

```bash
python scout.py --config config.yaml --dry-run
```

Force queue for testing:

```bash
python scout.py --config config.yaml --force
```

Send up to 5 queued memories:

```bash
python sender.py --config config.yaml --limit 5
```

Run hide server:

```bash
uvicorn hide_server:app --host 0.0.0.0 --port 8080
```

## Troubleshooting

- Immich request failures
  - Verify `IMMICH_API_KEY`
  - Verify `immich.base_url`
  - Test endpoint manually with the same host/key
- ntfy send failures
  - Verify `ntfy.base_url` and `ntfy.topic`
  - Confirm sender host can reach ntfy
- Empty queue
  - Lower `scout.threshold`
  - Use `--force` for connectivity checks
- Hide action does not work
  - Verify `scout.hide_action_url` points to reachable `hide_server`
  - Ensure notification action uses `POST`
- `POST /hide` is idempotent: any Immich `memory_id` can be hidden even if it was never queued (future scouts skip it)

## Data maintenance

Inspect queued rows:

```bash
sqlite3 data/queue.sqlite "select id,memory_id,score,status,created_at from queue order by id desc limit 20;"
```

Inspect hidden memories:

```bash
sqlite3 data/queue.sqlite "select memory_id,hidden_at from hidden order by hidden_at desc limit 20;"
```
