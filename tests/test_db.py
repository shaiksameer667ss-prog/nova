import uuid
from datetime import UTC, datetime

from nova.config import get_settings
from nova.memory.db import connect


def _ts() -> str:
    return datetime.now(UTC).isoformat()


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


def test_runs_include_lifecycle_columns(tmp_path):
    conn = connect(tmp_path / "fresh.sqlite3")
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }

    assert {"status", "finished_at", "error_type"} <= columns
    conn.close()


def test_legacy_runs_migrate_without_losing_existing_data(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(db_path)

    legacy.execute(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            arm TEXT NOT NULL,
            seed INTEGER NOT NULL,
            model TEXT NOT NULL,
            success INTEGER NOT NULL,
            verified_success INTEGER,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            wall_seconds REAL NOT NULL DEFAULT 0.0,
            git_sha TEXT,
            created_at TEXT NOT NULL,
            memory_injected INTEGER DEFAULT 0,
            memory_type TEXT,
            memory_item_id TEXT,
            memory_source_run_id TEXT,
            memory_sha256 TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            usage_complete INTEGER NOT NULL DEFAULT 0,
            termination_reason TEXT
        )
        """
    )
    legacy.execute(
        """
        INSERT INTO runs (
            id, task_id, arm, seed, model, success,
            verified_success, created_at, termination_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-run-1",
            "inventory_batch",
            "A",
            0,
            "test-model",
            1,
            1,
            "2026-01-01T00:00:00+00:00",
            "completed",
        ),
    )
    legacy.commit()
    legacy.close()

    conn = connect(db_path)
    row = conn.execute(
        "SELECT * FROM runs WHERE id = ?",
        ("legacy-run-1",),
    ).fetchone()

    assert row["status"] == "completed"
    assert row["finished_at"] is None
    assert row["error_type"] is None
    assert row["task_id"] == "inventory_batch"
    assert row["verified_success"] == 1
    assert row["termination_reason"] == "completed"
    conn.close()



def test_create_run_persists_running_state(tmp_path):
    from nova.memory.db import create_run

    conn = connect(tmp_path / "runs.sqlite3")
    create_run(
        conn,
        run_id="run-001",
        task_id="test_task",
        arm="A",
        seed=0,
        model="test-model",
    )

    row = conn.execute(
        "SELECT * FROM runs WHERE id = ?", ("run-001",)
    ).fetchone()

    assert row["status"] == "running"
    assert row["success"] == 0
    assert row["finished_at"] is None
    assert row["error_type"] is None
    conn.close()


def test_finish_run_records_completed_state(tmp_path):
    from nova.memory.db import create_run, finish_run

    conn = connect(tmp_path / "runs.sqlite3")
    create_run(
        conn,
        run_id="run-002",
        task_id="test_task",
        arm="A",
        seed=1,
        model="test-model",
    )

    finish_run(
        conn,
        "run-002",
        success=True,
        wall_seconds=2.5,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        usage_complete=True,
        termination_reason="completed",
        finished_at="2026-11-09T12:00:00+00:00",
    )

    row = conn.execute(
        "SELECT * FROM runs WHERE id = ?", ("run-002",)
    ).fetchone()

    assert row["status"] == "completed"
    assert row["success"] == 1
    assert row["finished_at"] == "2026-11-09T12:00:00+00:00"
    assert row["termination_reason"] == "completed"
    assert row["total_tokens"] == 15
    conn.close()


def test_fail_run_records_unexpected_exception(tmp_path):
    from nova.memory.db import create_run, fail_run

    conn = connect(tmp_path / "runs.sqlite3")
    create_run(
        conn,
        run_id="run-003",
        task_id="test_task",
        arm="A",
        seed=0,
        model="test-model",
    )

    changed = fail_run(
        conn,
        "run-003",
        error_type="RuntimeError",
        finished_at="2026-11-09T12:00:00+00:00",
    )

    row = conn.execute(
        "SELECT * FROM runs WHERE id = ?", ("run-003",)
    ).fetchone()

    assert changed is True
    assert row["status"] == "failed"
    assert row["success"] == 0
    assert row["error_type"] == "RuntimeError"
    assert row["finished_at"] == "2026-11-09T12:00:00+00:00"
    conn.close()


def test_recover_interrupted_runs_is_safe_and_idempotent(tmp_path):
    from nova.memory.db import (
        create_run,
        finish_run,
        recover_interrupted_runs,
    )

    conn = connect(tmp_path / "runs.sqlite3")

    create_run(
        conn,
        run_id="interrupted-run",
        task_id="test_task",
        arm="A",
        seed=0,
        model="test-model",
    )
    create_run(
        conn,
        run_id="completed-run",
        task_id="test_task",
        arm="A",
        seed=1,
        model="test-model",
    )

    finish_run(
        conn,
        "completed-run",
        success=True,
        wall_seconds=1.0,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        usage_complete=True,
        termination_reason="completed",
    )

    recovered = recover_interrupted_runs(conn)
    assert recovered == 1

    rows = {
        row["id"]: row
        for row in conn.execute(
            "SELECT * FROM runs"
        ).fetchall()
    }

    assert rows["interrupted-run"]["status"] == "interrupted"
    assert rows["interrupted-run"]["error_type"] == "ProcessInterrupted"
    assert rows["interrupted-run"]["finished_at"] is not None
    assert rows["completed-run"]["status"] == "completed"

    # A second recovery must not alter already recovered records.
    assert recover_interrupted_runs(conn) == 0
    conn.close()
