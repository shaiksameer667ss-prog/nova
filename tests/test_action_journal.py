import hashlib

import pytest

from nova.memory.db import (
    connect,
    create_action_execution,
    finish_action_execution,
    get_action_execution,
    start_action_execution,
)


def _request_hash():
    return hashlib.sha256(b"read_file:ledger.py").hexdigest()


def _create(conn, **overrides):
    values = {
        "execution_id": "exec-001",
        "run_id": "run-001",
        "step": 0,
        "action_name": "read_file",
        "effect": "read",
        "idempotency_key": "run-001:0",
        "request_summary": "read_file(path=<redacted>)",
        "request_sha256": _request_hash(),
    }
    values.update(overrides)
    create_action_execution(conn, **values)


def test_journal_table_is_created(tmp_path):
    conn = connect(tmp_path / "journal.db")
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "action_executions" in tables
    conn.close()


def test_action_starts_in_prepared_state(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "prepared"
    assert row["action_name"] == "read_file"
    assert row["effect"] == "read"
    assert row["request_sha256"] == _request_hash()
    conn.close()


def test_journal_persists_across_connections(tmp_path):
    db = tmp_path / "journal.db"
    conn = connect(db)
    _create(conn)
    conn.close()

    reopened = connect(db)
    row = get_action_execution(reopened, "exec-001")
    assert row is not None
    assert row["status"] == "prepared"
    reopened.close()


def test_action_transitions_to_executing(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)

    start_action_execution(conn, "exec-001")

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "executing"
    assert row["started_at"] is not None
    conn.close()


def test_action_can_finish_successfully(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    result_hash = hashlib.sha256(b"file contents").hexdigest()
    finish_action_execution(
        conn,
        "exec-001",
        status="succeeded",
        result_sha256=result_hash,
        result_length=13,
    )

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "succeeded"
    assert row["result_sha256"] == result_hash
    assert row["result_length"] == 13
    assert row["finished_at"] is not None
    conn.close()


def test_action_can_finish_as_failed(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    finish_action_execution(
        conn,
        "exec-001",
        status="failed",
        error_type="FileNotFoundError",
    )

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "failed"
    assert row["error_type"] == "FileNotFoundError"
    conn.close()


def test_action_can_finish_as_uncertain(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    finish_action_execution(
        conn,
        "exec-001",
        status="uncertain",
        error_type="ProcessInterrupted",
    )

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "uncertain"
    assert row["error_type"] == "ProcessInterrupted"
    conn.close()


def test_executing_action_remains_visible_after_reconnection(tmp_path):
    db = tmp_path / "journal.db"
    conn = connect(db)
    _create(conn)
    start_action_execution(conn, "exec-001")
    conn.close()

    reopened = connect(db)
    row = get_action_execution(reopened, "exec-001")
    assert row["status"] == "executing"
    assert row["finished_at"] is None
    reopened.close()


def test_duplicate_idempotency_key_is_rejected(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)

    with pytest.raises(ValueError, match="Duplicate"):
        _create(
            conn,
            execution_id="exec-002",
            step=1,
        )
    conn.close()


def test_duplicate_run_step_is_rejected(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)

    with pytest.raises(ValueError, match="Duplicate"):
        _create(
            conn,
            execution_id="exec-002",
            idempotency_key="run-001:1",
        )
    conn.close()


def test_start_requires_prepared_record(tmp_path):
    conn = connect(tmp_path / "journal.db")

    with pytest.raises(ValueError, match="prepared state"):
        start_action_execution(conn, "missing-execution")

    _create(conn)
    start_action_execution(conn, "exec-001")

    with pytest.raises(ValueError, match="prepared state"):
        start_action_execution(conn, "exec-001")

    conn.close()


def test_finish_requires_executing_record(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)

    with pytest.raises(ValueError, match="Only an executing action"):
        finish_action_execution(
            conn,
            "exec-001",
            status="succeeded",
        )

    conn.close()


def test_failed_and_uncertain_require_error_type(tmp_path):
    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    with pytest.raises(ValueError, match="requires error_type"):
        finish_action_execution(
            conn,
            "exec-001",
            status="failed",
        )

    with pytest.raises(ValueError, match="requires error_type"):
        finish_action_execution(
            conn,
            "exec-001",
            status="uncertain",
        )

    conn.close()


def test_invalid_hash_is_rejected(tmp_path):
    conn = connect(tmp_path / "journal.db")

    with pytest.raises(ValueError, match="SHA-256"):
        _create(conn, request_sha256="not-a-hash")

    conn.close()


def test_invalid_effect_is_rejected(tmp_path):
    conn = connect(tmp_path / "journal.db")

    with pytest.raises(ValueError, match="Invalid action effect"):
        _create(conn, effect="delete")

    conn.close()


def test_negative_step_is_rejected(tmp_path):
    conn = connect(tmp_path / "journal.db")

    with pytest.raises(ValueError, match="non-negative"):
        _create(conn, step=-1)

    conn.close()

def test_recovery_marks_prepared_action_failed(tmp_path):
    from nova.memory.db import recover_interrupted_actions

    conn = connect(tmp_path / "journal.db")
    _create(conn)

    result = recover_interrupted_actions(conn, "new-run")

    row = get_action_execution(conn, "exec-001")
    assert result == {"failed": 1, "uncertain": 0}
    assert row["status"] == "failed"
    assert row["error_type"] == "InterruptedBeforeDispatch"
    conn.close()


def test_recovery_marks_executing_action_uncertain(tmp_path):
    from nova.memory.db import recover_interrupted_actions

    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    result = recover_interrupted_actions(conn, "new-run")

    row = get_action_execution(conn, "exec-001")
    assert result == {"failed": 0, "uncertain": 1}
    assert row["status"] == "uncertain"
    assert row["error_type"] == "ProcessInterrupted"
    conn.close()


def test_recovery_does_not_touch_current_run(tmp_path):
    from nova.memory.db import recover_interrupted_actions

    conn = connect(tmp_path / "journal.db")
    _create(conn)

    result = recover_interrupted_actions(conn, "run-001")

    row = get_action_execution(conn, "exec-001")
    assert result == {"failed": 0, "uncertain": 0}
    assert row["status"] == "prepared"
    conn.close()


def test_recovery_is_idempotent(tmp_path):
    from nova.memory.db import recover_interrupted_actions

    conn = connect(tmp_path / "journal.db")
    _create(conn)
    start_action_execution(conn, "exec-001")

    first = recover_interrupted_actions(conn, "new-run")
    second = recover_interrupted_actions(conn, "new-run")

    assert first == {"failed": 0, "uncertain": 1}
    assert second == {"failed": 0, "uncertain": 0}
    conn.close()


def test_recovery_rejects_empty_current_run_id(tmp_path):
    from nova.memory.db import recover_interrupted_actions

    conn = connect(tmp_path / "journal.db")

    with pytest.raises(ValueError, match="must not be empty"):
        recover_interrupted_actions(conn, "")

    conn.close()
