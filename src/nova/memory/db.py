import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    plan        TEXT,
    actions     TEXT,
    outcome     TEXT,
    success     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id                  TEXT PRIMARY KEY,
    version             INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    source_task_ids     TEXT NOT NULL,
    trigger_conditions  TEXT,
    procedure           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'candidate',
    success_count       INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    arm          TEXT NOT NULL,
    seed         INTEGER NOT NULL,
    model        TEXT NOT NULL,
    success      INTEGER NOT NULL,
    verified_success INTEGER,
    cost_usd     REAL NOT NULL DEFAULT 0.0,
    wall_seconds REAL NOT NULL DEFAULT 0.0,
    git_sha      TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_log (
    id             TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    skill_id       TEXT NOT NULL,
    score          REAL NOT NULL,
    was_applicable INTEGER,
    was_applied    INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # Migrate existing databases safely.
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    if "verified_success" not in columns:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN verified_success INTEGER"
        )
        conn.commit()
        
    return conn