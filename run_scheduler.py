#!/usr/bin/env python3
"""Generate a crontab from config.yaml and exec supercronic (stdout-friendly cron)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from shlex import quote

from memories_app.config import load_config


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")
    config = load_config(config_path)
    scout_cron = config.scheduler.scout_cron.strip()
    sender_cron = config.scheduler.sender_cron.strip()
    if not scout_cron or not sender_cron:
        print("scheduler: scout_cron and sender_cron must be non-empty", file=sys.stderr)
        sys.exit(1)

    quoted_config = quote(config_path)
    lines = [
        f"{scout_cron} /usr/local/bin/python /app/scout.py --config {quoted_config}",
        f"{sender_cron} /usr/local/bin/python /app/sender.py --config {quoted_config}",
    ]
    crontab_path = Path("/tmp/supercronic.crontab")
    crontab_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    os.execvp("supercronic", ["supercronic", "-passthrough-logs", str(crontab_path)])


if __name__ == "__main__":
    main()
