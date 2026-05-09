from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS queue (
          id INTEGER PRIMARY KEY,
          memory_id TEXT NOT NULL,
          memory_date TEXT NOT NULL,
          year INTEGER NOT NULL,
          asset_id TEXT NOT NULL,
          score INTEGER NOT NULL,
          city TEXT,
          caption TEXT NOT NULL,
          status TEXT NOT NULL,
          enriched_at TEXT,
          sent_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(memory_id)
        );

        CREATE TABLE IF NOT EXISTS hidden (
          memory_id TEXT PRIMARY KEY,
          hidden_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    connection.commit()
