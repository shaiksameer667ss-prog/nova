import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT NOT NULL,
    created_at TEXT NOT NULL, plan TEXT, actions TEXT, outcome TEXT, success INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at TEXT NOT NULL,
    source_task_ids TEXT NOT NULL, source_run_id TEXT, source_episode_id TEXT,
    trigger_conditions TEXT, procedure TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
    success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS retrieval_log (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL, skill_id TEXT NOT NULL,
    score REAL NOT NULL, was_applicable INTEGER, was_applied INTEGER NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, arm TEXT NOT NULL, seed INTEGER NOT NULL,
    model TEXT NOT NULL, success INTEGER NOT NULL, verified_success INTEGER,
    cost_usd REAL NOT NULL DEFAULT 0.0, wall_seconds REAL NOT NULL DEFAULT 0.0,
    git_sha TEXT, created_at TEXT NOT NULL,
    memory_injected INTEGER DEFAULT 0, memory_type TEXT, memory_item_id TEXT,
    memory_source_run_id TEXT, memory_sha256 TEXT,
    prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
    usage_complete INTEGER NOT NULL DEFAULT 0,
    termination_reason TEXT
);

CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY, run_id TEXT, purpose TEXT NOT NULL,
    model TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
    status TEXT NOT NULL, usage_complete INTEGER NOT NULL DEFAULT 0, usage_json TEXT,
    created_at TEXT NOT NULL
);
"""

def _ensure_column(conn, table, column, col_type):
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()

def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    _ensure_column(conn, "episodes", "run_id", "TEXT")
    _ensure_column(conn, "skills", "source_run_id", "TEXT")
    _ensure_column(conn, "skills", "source_episode_id", "TEXT")
    _ensure_column(conn, "runs", "memory_injected", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "memory_type", "TEXT")
    _ensure_column(conn, "runs", "memory_item_id", "TEXT")
    _ensure_column(conn, "runs", "memory_source_run_id", "TEXT")
    _ensure_column(conn, "runs", "memory_sha256", "TEXT")
    _ensure_column(conn, "runs", "prompt_tokens", "INTEGER")
    _ensure_column(conn, "runs", "completion_tokens", "INTEGER")
    _ensure_column(conn, "runs", "total_tokens", "INTEGER")
    _ensure_column(conn, "runs", "usage_complete", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "runs", "termination_reason", "TEXT")

    return conn