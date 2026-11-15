import sqlite3
from datetime import UTC, datetime
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
    termination_reason TEXT,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK(status IN ('running', 'completed', 'failed', 'interrupted')),
    finished_at TEXT,
    error_type TEXT
);

CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY, run_id TEXT, purpose TEXT NOT NULL,
    model TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
    status TEXT NOT NULL, usage_complete INTEGER NOT NULL DEFAULT 0, usage_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_executions (
    execution_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL CHECK(step >= 0),
    action_name TEXT NOT NULL,
    effect TEXT NOT NULL CHECK(effect IN ('read', 'write', 'control')),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_summary TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    status TEXT NOT NULL CHECK(
        status IN ('prepared', 'executing', 'succeeded', 'failed', 'uncertain')
    ),
    result_sha256 TEXT,
    result_length INTEGER CHECK(result_length IS NULL OR result_length >= 0),
    error_type TEXT,
    error_fingerprint TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    write_path TEXT,
    expected_content_sha256 TEXT,
    expected_content_length INTEGER,
    write_verified_at TEXT,
    write_observed_sha256 TEXT,
    write_observed_length INTEGER,
    write_verification_run_id TEXT,
    write_superseded_at TEXT,
    write_superseded_by_execution_id TEXT,
    UNIQUE(run_id, step)
);

CREATE INDEX IF NOT EXISTS idx_action_executions_run
ON action_executions(run_id, step);

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
    _ensure_column(
        conn,
        "runs",
        "status",
        "TEXT NOT NULL DEFAULT 'completed' "
        "CHECK(status IN ('running', 'completed', 'failed', 'interrupted'))",
    )
    _ensure_column(conn, "runs", "finished_at", "TEXT")
    _ensure_column(conn, "runs", "error_type", "TEXT")
    _ensure_column(conn, "action_executions", "write_path", "TEXT")
    _ensure_column(
        conn, "action_executions", "expected_content_sha256", "TEXT"
    )
    _ensure_column(
        conn, "action_executions", "expected_content_length", "INTEGER"
    )
    _ensure_column(conn, "action_executions", "write_verified_at", "TEXT")
    _ensure_column(
        conn, "action_executions", "write_observed_sha256", "TEXT"
    )
    _ensure_column(
        conn, "action_executions", "write_observed_length", "INTEGER"
    )
    _ensure_column(
        conn, "action_executions", "write_verification_run_id", "TEXT"
    )
    _ensure_column(conn, "action_executions", "write_superseded_at", "TEXT")
    _ensure_column(
        conn, "action_executions", "write_superseded_by_execution_id", "TEXT"
    )

    return conn


def _journal_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _validate_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest.")
    try:
        int(value, 16)
    except ValueError:
        raise ValueError(
            f"{field} must be a 64-character SHA-256 hex digest."
        ) from None


def create_action_execution(
    conn: sqlite3.Connection,
    *,
    execution_id: str,
    run_id: str,
    step: int,
    action_name: str,
    effect: str,
    idempotency_key: str,
    request_summary: str,
    request_sha256: str,
    write_path: str | None = None,
    expected_content_sha256: str | None = None,
    expected_content_length: int | None = None,
) -> None:
    """Durably record an action intent before any tool side effect."""
    if not isinstance(step, int) or isinstance(step, bool) or step < 0:
        raise ValueError("step must be a non-negative integer.")
    if effect not in {"read", "write", "control"}:
        raise ValueError(f"Invalid action effect: {effect!r}")

    for name, value in (
        ("execution_id", execution_id),
        ("run_id", run_id),
        ("action_name", action_name),
        ("idempotency_key", idempotency_key),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be empty.")

    if not isinstance(request_summary, str):
        raise TypeError("request_summary must be a string.")

    _validate_sha256(request_sha256, "request_sha256")

    write_metadata = (
        write_path,
        expected_content_sha256,
        expected_content_length,
    )
    if any(value is not None for value in write_metadata):
        if not all(value is not None for value in write_metadata):
            raise ValueError("Write verification metadata must be complete.")
        if action_name != "write_file" or effect != "write":
            raise ValueError("Write verification metadata requires write_file.")
        if (
            not isinstance(write_path, str)
            or not write_path
            or write_path.startswith("/")
            or "\\" in write_path
            or any(part in {"", ".", ".."} for part in write_path.split("/"))
        ):
            raise ValueError("write_path must be a normalized relative path.")
        _validate_sha256(
            expected_content_sha256,
            "expected_content_sha256",
        )
        if (
            not isinstance(expected_content_length, int)
            or isinstance(expected_content_length, bool)
            or expected_content_length < 0
        ):
            raise ValueError(
                "expected_content_length must be a non-negative integer."
            )

    try:
        conn.execute(
            """
            INSERT INTO action_executions (
                execution_id, run_id, step, action_name, effect,
                idempotency_key, request_summary, request_sha256,
                status, created_at, write_path, expected_content_sha256,
                expected_content_length
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?)
            """,
            (
                execution_id, run_id, step, action_name, effect,
                idempotency_key, request_summary, request_sha256,
                _journal_timestamp(),
                write_path,
                expected_content_sha256,
                expected_content_length,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(
            "Duplicate execution ID, run step, or idempotency key."
        ) from exc


def start_action_execution(
    conn: sqlite3.Connection,
    execution_id: str,
) -> None:
    """Commit the executing state before dispatching the tool."""
    cursor = conn.execute(
        """
        UPDATE action_executions
        SET status = 'executing', started_at = ?
        WHERE execution_id = ? AND status = 'prepared'
        """,
        (_journal_timestamp(), execution_id),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise ValueError(
            "Action execution must exist in prepared state before it starts."
        )
    conn.commit()


def finish_action_execution(
    conn: sqlite3.Connection,
    execution_id: str,
    *,
    status: str,
    result_sha256: str | None = None,
    result_length: int | None = None,
    error_type: str | None = None,
    error_fingerprint: str | None = None,
) -> None:
    """Commit a terminal outcome without storing raw tool output."""
    if status not in {"succeeded", "failed", "uncertain"}:
        raise ValueError("Invalid terminal action status.")

    if result_sha256 is not None:
        _validate_sha256(result_sha256, "result_sha256")

    if result_length is not None and (
        not isinstance(result_length, int)
        or isinstance(result_length, bool)
        or result_length < 0
    ):
        raise ValueError("result_length must be a non-negative integer.")

    if status in {"failed", "uncertain"} and not error_type:
        raise ValueError(f"{status} status requires error_type.")

    if error_fingerprint is not None:
        _validate_sha256(error_fingerprint, "error_fingerprint")

    cursor = conn.execute(
        """
        UPDATE action_executions
        SET status = ?, result_sha256 = ?, result_length = ?,
            error_type = ?, error_fingerprint = ?, finished_at = ?
        WHERE execution_id = ? AND status = 'executing'
        """,
        (
            status, result_sha256, result_length,
            error_type, error_fingerprint, _journal_timestamp(),
            execution_id,
        ),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise ValueError(
            "Only an executing action can transition to a terminal status."
        )
    conn.commit()


def get_action_execution(
    conn: sqlite3.Connection,
    execution_id: str,
) -> sqlite3.Row | None:
    """Return a journal record, or None when it does not exist."""
    return conn.execute(
        "SELECT * FROM action_executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()




def get_unresolved_uncertain_writes(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return uncertain write intents that have not been verified."""
    return conn.execute(
        """
        SELECT execution_id, run_id, write_path,
               expected_content_sha256, expected_content_length
        FROM action_executions
        WHERE action_name = 'write_file'
          AND effect = 'write'
          AND status = 'uncertain'
          AND write_verified_at IS NULL
          AND write_superseded_at IS NULL
        ORDER BY rowid
        """
    ).fetchall()


def mark_uncertain_write_verified(
    conn: sqlite3.Connection,
    execution_id: str,
    observed_sha256: str,
    observed_length: int,
    verification_run_id: str,
) -> bool:
    """Persist exact readback verification without changing action outcome."""
    _validate_sha256(observed_sha256, "observed_sha256")
    if (
        not isinstance(observed_length, int)
        or isinstance(observed_length, bool)
        or observed_length < 0
    ):
        raise ValueError("observed_length must be a non-negative integer.")
    if not isinstance(verification_run_id, str) or not verification_run_id.strip():
        raise ValueError("verification_run_id must not be empty.")

    cursor = conn.execute(
        """
        UPDATE action_executions
        SET write_verified_at = ?,
            write_observed_sha256 = ?,
            write_observed_length = ?,
            write_verification_run_id = ?
        WHERE execution_id = ?
          AND action_name = 'write_file'
          AND effect = 'write'
          AND status = 'uncertain'
          AND write_verified_at IS NULL
          AND write_superseded_at IS NULL
          AND expected_content_sha256 = ?
          AND expected_content_length = ?
        """,
        (
            _journal_timestamp(),
            observed_sha256,
            observed_length,
            verification_run_id,
            execution_id,
            observed_sha256,
            observed_length,
        ),
    )
    conn.commit()
    return cursor.rowcount == 1



def supersede_uncertain_writes(
    conn: sqlite3.Connection,
    write_path: str,
    superseding_execution_id: str,
) -> list[str]:
    """Supersede older uncertain writes after a newer full write is confirmed."""
    if not isinstance(write_path, str) or not write_path.strip():
        raise ValueError("write_path must not be empty.")
    if (
        write_path.startswith("/")
        or "\\" in write_path
        or any(part in {"", ".", ".."} for part in write_path.split("/"))
    ):
        raise ValueError("write_path must be normalized and workspace-relative.")
    if not isinstance(superseding_execution_id, str) or not superseding_execution_id.strip():
        raise ValueError("superseding_execution_id must not be empty.")

    current = conn.execute(
        """
        SELECT rowid AS journal_order, action_name, effect, status,
               write_path, write_verified_at
        FROM action_executions
        WHERE execution_id = ?
        """,
        (superseding_execution_id,),
    ).fetchone()

    if (
        current is None
        or current["action_name"] != "write_file"
        or current["effect"] != "write"
        or current["write_path"] != write_path
        or not (
            current["status"] == "succeeded"
            or (
                current["status"] == "uncertain"
                and current["write_verified_at"] is not None
            )
        )
    ):
        raise ValueError(
            "Superseding action must be a successful or verified write "
            "for the same path."
        )

    ordering = " AND rowid < ?"
    params = (
        write_path,
        superseding_execution_id,
        current["journal_order"],
    )

    rows = conn.execute(
        """
        SELECT execution_id
        FROM action_executions
        WHERE action_name = 'write_file'
          AND effect = 'write'
          AND status = 'uncertain'
          AND write_path = ?
          AND write_verified_at IS NULL
          AND write_superseded_at IS NULL
          AND execution_id != ?
        """ + ordering + """
        ORDER BY rowid
        """,
        params,
    ).fetchall()

    ids = [row["execution_id"] for row in rows]
    if not ids:
        return []

    conn.execute(
        """
        UPDATE action_executions
        SET write_superseded_at = ?,
            write_superseded_by_execution_id = ?
        WHERE action_name = 'write_file'
          AND effect = 'write'
          AND status = 'uncertain'
          AND write_path = ?
          AND write_verified_at IS NULL
          AND write_superseded_at IS NULL
          AND execution_id != ?
        """ + ordering,
        (_journal_timestamp(), superseding_execution_id) + params,
    )
    conn.commit()
    return ids




def recover_superseded_uncertain_writes(
    conn: sqlite3.Connection,
) -> list[str]:
    """Reconcile older uncertainty against durable later confirmed writes."""
    confirmed = conn.execute(
        """
        SELECT execution_id, write_path
        FROM action_executions
        WHERE action_name = 'write_file'
          AND effect = 'write'
          AND write_path IS NOT NULL
          AND (
              status = 'succeeded'
              OR (status = 'uncertain' AND write_verified_at IS NOT NULL)
          )
        ORDER BY rowid
        """
    ).fetchall()

    superseded_ids = []
    for row in confirmed:
        superseded_ids.extend(
            supersede_uncertain_writes(
                conn,
                row["write_path"],
                row["execution_id"],
            )
        )

    return superseded_ids


def recover_interrupted_actions(
    conn: sqlite3.Connection,
    current_run_id: str,
) -> dict[str, int]:
    """
    Classify unfinished actions from previous runs.

    Call only after acquiring the exclusive NOVA runtime lock.
    Prepared actions were never dispatched; executing actions have
    an uncertain side-effect outcome and must not be replayed.
    """
    if not isinstance(current_run_id, str) or not current_run_id.strip():
        raise ValueError("current_run_id must not be empty.")

    rows = conn.execute(
        """
        SELECT execution_id, status
        FROM action_executions
        WHERE run_id != ?
          AND status IN ('prepared', 'executing')
        """,
        (current_run_id,),
    ).fetchall()

    recovered = {"failed": 0, "uncertain": 0}

    for row in rows:
        if row["status"] == "prepared":
            new_status = "failed"
            error_type = "InterruptedBeforeDispatch"
        else:
            new_status = "uncertain"
            error_type = "ProcessInterrupted"

        cursor = conn.execute(
            """
            UPDATE action_executions
            SET status = ?, error_type = ?, finished_at = ?
            WHERE execution_id = ? AND status = ?
            """,
            (
                new_status,
                error_type,
                _journal_timestamp(),
                row["execution_id"],
                row["status"],
            ),
        )

        if cursor.rowcount == 1:
            recovered[new_status] += 1

    conn.commit()
    return recovered



def create_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    arm: str,
    seed: int,
    model: str,
) -> None:
    """Persist a new run before its first model call."""
    for name, value in (
        ("run_id", run_id),
        ("task_id", task_id),
        ("arm", arm),
        ("model", model),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be empty.")

    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer.")

    try:
        conn.execute(
            """
            INSERT INTO runs (
                id, task_id, arm, seed, model, success,
                created_at, status
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, 'running')
            """,
            (
                run_id,
                task_id,
                arm,
                seed,
                model,
                _journal_timestamp(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(f"Run already exists: {run_id}") from exc


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    success: bool,
    wall_seconds: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    usage_complete: bool,
    termination_reason: str,
    finished_at: str | None = None,
) -> None:
    """Finalize a normally terminated run and persist its measurements."""
    if not isinstance(success, bool):
        raise TypeError("success must be a boolean.")
    if not isinstance(usage_complete, bool):
        raise TypeError("usage_complete must be a boolean.")
    if (
        not isinstance(wall_seconds, (int, float))
        or isinstance(wall_seconds, bool)
        or wall_seconds < 0
    ):
        raise ValueError("wall_seconds must be a non-negative number.")
    if not isinstance(termination_reason, str) or not termination_reason:
        raise ValueError("termination_reason must not be empty.")

    for name, value in (
        ("prompt_tokens", prompt_tokens),
        ("completion_tokens", completion_tokens),
        ("total_tokens", total_tokens),
    ):
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"{name} must be a non-negative integer or None.")

    cursor = conn.execute(
        """
        UPDATE runs
        SET status = 'completed',
            success = ?,
            wall_seconds = ?,
            prompt_tokens = ?,
            completion_tokens = ?,
            total_tokens = ?,
            usage_complete = ?,
            termination_reason = ?,
            finished_at = ?,
            error_type = NULL
        WHERE id = ? AND status = 'running'
        """,
        (
            int(success),
            wall_seconds,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            int(usage_complete),
            termination_reason,
            finished_at or _journal_timestamp(),
            run_id,
        ),
    )

    if cursor.rowcount != 1:
        conn.rollback()
        raise ValueError("Only an existing running run can be completed.")

    conn.commit()


def fail_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    error_type: str,
    finished_at: str | None = None,
) -> bool:
    """Record an unexpected controller failure for a running task."""
    if not isinstance(error_type, str) or not error_type.strip():
        raise ValueError("error_type must not be empty.")

    cursor = conn.execute(
        """
        UPDATE runs
        SET status = 'failed',
            success = 0,
            error_type = ?,
            finished_at = ?
        WHERE id = ? AND status = 'running'
        """,
        (error_type, finished_at or _journal_timestamp(), run_id),
    )

    conn.commit()
    return cursor.rowcount == 1


def recover_interrupted_runs(conn: sqlite3.Connection) -> int:
    """Mark runs left active by an earlier process as interrupted."""
    cursor = conn.execute(
        """
        UPDATE runs
        SET status = 'interrupted',
            error_type = 'ProcessInterrupted',
            finished_at = ?
        WHERE status = 'running'
        """,
        (_journal_timestamp(),),
    )

    recovered = cursor.rowcount
    conn.commit()
    return recovered
