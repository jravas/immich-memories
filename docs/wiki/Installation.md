# Installation

## Prerequisites

- Python 3.12+
- Network reachability to:
  - Immich server
  - ntfy server
- An Immich API key for the target user

## Local Python setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variable:

```bash
export IMMICH_API_KEY="YOUR_IMMICH_API_KEY"
```

4. Review `config.yaml` and adjust URLs and threshold.

## First dry run

Use `--dry-run` to verify connectivity and scoring behavior without writing queue rows:

```bash
python scout.py --config config.yaml --dry-run
```

## Run services with Docker Compose

```bash
docker compose up --build
```

Compose services (default):

- `scheduler`: runs `scout` and `sender` on the schedules in `config.yaml` using supercronic
- `hide-server`: HTTP endpoint for the ntfy “Hide forever” action

Optional one-shot runs (Docker Compose `manual` profile):

```bash
docker compose --profile manual run --rm scout
docker compose --profile manual run --rm sender
```

Persistent queue data is stored in `./data`.
