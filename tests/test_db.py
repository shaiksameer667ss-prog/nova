import uuid
from datetime import datetime, timezone

from nova.config import get_settings
from nova.memory.db import connect


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_schema_creates_all_tables(tmp_path):
    conn = connect(tmp_path / "test.sqlite3")
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"episodes", "skills", "runs", "retrieval_log"} <= tables
    conn.close()


def test_insert_and_read_episode(tmp_path):
    conn = connect(tmp_path / "test.sqlite3")
    eid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO episodes (id, task_id, created_at, plan, actions, outcome, success) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, "task_001", _ts(), "p", "a", "ok", 1),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["task_id"] == "task_001"
    assert row["success"] == 1
    conn.close()


def test_insert_and_read_skill(tmp_path):
    conn = connect(tmp_path / "test.sqlite3")
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO skills (id, version, created_at, source_task_ids, "
        "trigger_conditions, procedure, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, 1, _ts(), '["task_001"]', "{}", "do the thing", "candidate"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM skills WHERE id = ?", (sid,)).fetchone()
    assert row["status"] == "candidate"
    assert row["version"] == 1
    conn.close()


def test_settings_db_path_used_by_connect():
    s = get_settings()
    conn = connect(s.db)
    assert conn is not None
    conn.close()


def test_runs_has_verified_success_column(tmp_path):
    conn = connect(tmp_path / "test.sqlite3")
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    assert "verified_success" in columns
    conn.close()