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

def test_uncertain_write_metadata_survives_process_recovery(tmp_path):
    from nova.memory.db import get_unresolved_uncertain_writes, recover_interrupted_actions

    db = tmp_path / "journal.db"
    expected = b"persistent content"
    digest = hashlib.sha256(expected).hexdigest()

    conn = connect(db)
    _create(
        conn,
        action_name="write_file",
        effect="write",
        write_path="nested/result.txt",
        expected_content_sha256=digest,
        expected_content_length=len(expected),
    )
    start_action_execution(conn, "exec-001")
    conn.close()

    reopened = connect(db)
    recovered = recover_interrupted_actions(reopened, "new-run")
    pending = get_unresolved_uncertain_writes(reopened)

    assert recovered == {"failed": 0, "uncertain": 1}
    assert len(pending) == 1
    assert pending[0]["execution_id"] == "exec-001"
    assert pending[0]["write_path"] == "nested/result.txt"
    assert pending[0]["expected_content_sha256"] == digest
    assert pending[0]["expected_content_length"] == len(expected)
    assert get_action_execution(reopened, "exec-001")["status"] == "uncertain"
    reopened.close()


def test_uncertain_write_verification_requires_exact_digest_and_length(tmp_path):
    from nova.memory.db import (
        get_unresolved_uncertain_writes,
        mark_uncertain_write_verified,
    )

    conn = connect(tmp_path / "journal.db")
    expected = b"verified content"
    digest = hashlib.sha256(expected).hexdigest()

    _create(
        conn,
        action_name="write_file",
        effect="write",
        write_path="result.txt",
        expected_content_sha256=digest,
        expected_content_length=len(expected),
    )
    start_action_execution(conn, "exec-001")
    finish_action_execution(
        conn,
        "exec-001",
        status="uncertain",
        error_type="ProcessInterrupted",
    )

    wrong_digest = hashlib.sha256(b"incorrect").hexdigest()
    assert mark_uncertain_write_verified(
        conn, "exec-001", wrong_digest, len(b"incorrect"), "verification-run"
    ) is False
    assert len(get_unresolved_uncertain_writes(conn)) == 1

    assert mark_uncertain_write_verified(
        conn, "exec-001", digest, len(expected), "verification-run"
    ) is True

    row = get_action_execution(conn, "exec-001")
    assert row["status"] == "uncertain"
    assert row["write_verified_at"] is not None
    assert row["write_observed_sha256"] == digest
    assert row["write_observed_length"] == len(expected)
    assert row["write_verification_run_id"] == "verification-run"
    assert get_unresolved_uncertain_writes(conn) == []
    conn.close()

def test_successful_newer_write_supersedes_older_uncertain_write(tmp_path):
    from nova.memory.db import (
        get_unresolved_uncertain_writes,
        supersede_uncertain_writes,
    )

    conn = connect(tmp_path / "journal.db")
    old_content = b"old version"
    new_content = b"new version"

    _create(
        conn,
        execution_id="exec-old",
        run_id="run-old",
        step=0,
        action_name="write_file",
        effect="write",
        idempotency_key="run-old:0",
        write_path="result.txt",
        expected_content_sha256=hashlib.sha256(old_content).hexdigest(),
        expected_content_length=len(old_content),
    )
    start_action_execution(conn, "exec-old")
    finish_action_execution(
        conn, "exec-old", status="uncertain", error_type="OSError"
    )

    _create(
        conn,
        execution_id="exec-new",
        run_id="run-new",
        step=0,
        action_name="write_file",
        effect="write",
        idempotency_key="run-new:0",
        write_path="result.txt",
        expected_content_sha256=hashlib.sha256(new_content).hexdigest(),
        expected_content_length=len(new_content),
    )
    start_action_execution(conn, "exec-new")
    finish_action_execution(
        conn,
        "exec-new",
        status="succeeded",
        result_sha256=hashlib.sha256(b"wrote result.txt").hexdigest(),
        result_length=len(b"wrote result.txt"),
    )

    # Equal timestamps across runs must still use journal insertion order.
    conn.execute(
        "UPDATE action_executions SET created_at = 'same-timestamp'"
    )
    conn.commit()

    superseded = supersede_uncertain_writes(conn, "result.txt", "exec-new")
    old_row = get_action_execution(conn, "exec-old")

    assert superseded == ["exec-old"]
    assert old_row["status"] == "uncertain"
    assert old_row["write_superseded_at"] is not None
    assert old_row["write_superseded_by_execution_id"] == "exec-new"
    assert get_unresolved_uncertain_writes(conn) == []
    conn.close()

def test_startup_reconciles_supersession_after_confirmed_write(tmp_path):
    from nova.memory.db import (
        get_unresolved_uncertain_writes,
        recover_superseded_uncertain_writes,
    )

    conn = connect(tmp_path / "journal.db")
    content = b"latest content"
    digest = hashlib.sha256(content).hexdigest()

    _create(
        conn,
        execution_id="old-write",
        run_id="old-run",
        step=0,
        action_name="write_file",
        effect="write",
        idempotency_key="old-run:0",
        write_path="result.txt",
        expected_content_sha256=hashlib.sha256(b"old").hexdigest(),
        expected_content_length=3,
    )
    start_action_execution(conn, "old-write")
    finish_action_execution(
        conn, "old-write", status="uncertain", error_type="OSError"
    )

    _create(
        conn,
        execution_id="confirmed-write",
        run_id="new-run",
        step=0,
        action_name="write_file",
        effect="write",
        idempotency_key="new-run:0",
        write_path="result.txt",
        expected_content_sha256=digest,
        expected_content_length=len(content),
    )
    start_action_execution(conn, "confirmed-write")
    finish_action_execution(
        conn,
        "confirmed-write",
        status="succeeded",
        result_sha256=hashlib.sha256(b"write result").hexdigest(),
        result_length=len(b"write result"),
    )

    conn.execute(
        "UPDATE action_executions SET created_at = 'same-timestamp'"
    )
    conn.commit()

    assert recover_superseded_uncertain_writes(conn) == ["old-write"]
    old = get_action_execution(conn, "old-write")
    assert old["status"] == "uncertain"
    assert old["write_superseded_by_execution_id"] == "confirmed-write"
    assert get_unresolved_uncertain_writes(conn) == []
    assert recover_superseded_uncertain_writes(conn) == []
    conn.close()
