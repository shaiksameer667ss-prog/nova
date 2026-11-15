from unittest.mock import MagicMock, patch

from nova.config import Settings
from nova.controller.loop import run_task
from nova.tools import file_ops


def _settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "journal.db",
        max_steps=5,
        temperature=0.2,
    )


def _usage():
    return {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "usage_complete": True,
        "usage_json": "{}",
        "finish_reason": "stop",
    }


def test_real_file_write_is_recorded_as_succeeded(tmp_path):
    settings = _settings(tmp_path)

    outputs = [
        '{"action":"write_file","path":"result.txt","content":"NOVA works"}',
        '{"action":"done","summary":"File created"}',
    ]

    with patch("nova.controller.loop.ModelClient") as MockClient:
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task("Create result.txt", settings)

    target = settings.workspace / "result.txt"
    assert target.read_text(encoding="utf-8") == "NOVA works"


    import sqlite3
    db = sqlite3.connect(settings.db)
    row = db.execute(
        """
        SELECT action_name, effect, status, result_sha256, request_summary
        FROM action_executions
        WHERE run_id = ?
        ORDER BY step
        """,
        (result["run_id"],),
    ).fetchall()

    assert len(row) == 2
    assert row[0][0:3] == ("write_file", "write", "succeeded")
    assert row[0][3] is not None
    assert "NOVA works" not in row[0][4]
    assert row[1][0:3] == ("done", "control", "succeeded")
    db.close()


def test_write_with_lost_confirmation_is_recorded_uncertain(tmp_path):
    settings = _settings(tmp_path)
    original_replace = file_ops.os.replace

    def replace_then_lose_confirmation(source, destination):
        original_replace(source, destination)
        raise OSError("simulated lost confirmation")

    outputs = [
        '{"action":"write_file","path":"result.txt","content":"committed"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"done","summary":"Finished"}',
    ]

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch.object(
            file_ops.os,
            "replace",
            side_effect=replace_then_lose_confirmation,
        ),
    ):
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task("Create result.txt", settings)

    assert result["agent_success"] is False
    assert result["completion_gate_blocked"] is True

    # The filesystem side effect happened, but the controller lost confirmation.
    assert (
        settings.workspace / "result.txt"
    ).read_text(encoding="utf-8") == "committed"

    import sqlite3
    db = sqlite3.connect(settings.db)
    row = db.execute(
        """
        SELECT status, error_type, result_sha256
        FROM action_executions
        WHERE run_id = ? AND action_name = 'write_file'
        """,
        (result["run_id"],),
    ).fetchone()

    assert row == ("uncertain", "OSError", None)
    db.close()

def test_startup_recovers_old_actions_without_replaying_them(tmp_path):
    import hashlib
    import sqlite3

    from nova.memory.db import (
        connect,
        create_action_execution,
        start_action_execution,
    )

    settings = _settings(tmp_path)
    conn = connect(settings.db)

    digest = hashlib.sha256(b"write_file:important.txt").hexdigest()

    def add_old_action(execution_id, run_id, step, status):
        create_action_execution(
            conn,
            execution_id=execution_id,
            run_id=run_id,
            step=step,
            action_name="write_file",
            effect="write",
            idempotency_key=f"{run_id}:{step}",
            request_summary="write_file(fields=content,path)",
            request_sha256=digest,
        )
        if status == "executing":
            start_action_execution(conn, execution_id)

    add_old_action("old-prepared", "old-run-1", 0, "prepared")
    add_old_action("old-executing", "old-run-2", 0, "executing")
    conn.close()

    outputs = [
        '{"action":"done","summary":"recovery complete"}',
        '{"action":"done","summary":"recovery complete"}',
    ]

    with patch("nova.controller.loop.ModelClient") as MockClient:
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task("Check journal recovery", settings)

    assert result["agent_success"] is False
    assert result["completion_gate_blocked"] is True
    assert result["stop_reason"] == "done_rejected"

    assert result["recovered_actions"] == {
        "failed": 1,
        "uncertain": 1,
    }

    db = sqlite3.connect(settings.db)
    rows = dict(
        db.execute(
            """
            SELECT execution_id, status
            FROM action_executions
            WHERE execution_id IN ('old-prepared', 'old-executing')
            """
        ).fetchall()
    )

    assert rows == {
        "old-prepared": "failed",
        "old-executing": "uncertain",
    }

    # Recovery records uncertainty; it does not replay the old write.
    assert not (settings.workspace / "important.txt").exists()
    db.close()



def test_process_interruption_recovers_executing_write_without_replay(tmp_path):
    import hashlib
    import os
    import sqlite3
    import subprocess
    import sys
    import textwrap
    import time
    from pathlib import Path

    import pytest

    from nova.controller.loop import _dispatch as original_dispatch

    settings = _settings(tmp_path)
    ready = tmp_path / "child.ready"
    dispatch_count = tmp_path / "dispatch.count"
    target = settings.workspace / "important.txt"

    child_code = textwrap.dedent("""
        import json
        import sys
        import time
        from pathlib import Path
        from unittest.mock import patch

        from nova.config import Settings
        from nova.controller import loop

        workspace = Path(sys.argv[1])
        db_path = Path(sys.argv[2])
        ready = Path(sys.argv[3])
        dispatch_count = Path(sys.argv[4])

        settings = Settings(
            base_url="http://localhost:11434/v1",
            api_key="test",
            model="test-model",
            workspace=workspace,
            db=db_path,
            max_steps=5,
            temperature=0.2,
        )

        class FakeClient:
            def chat_with_usage(self, *args, **kwargs):
                action = {
                    "action": "write_file",
                    "path": "important.txt",
                    "content": "write happened before process termination",
                }
                usage = {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "usage_complete": True,
                    "usage_json": "{}",
                    "finish_reason": "stop",
                }
                return json.dumps(action), usage, "success"

            def close(self):
                pass

        real_dispatch = loop._dispatch

        def crash_after_dispatch(action, active_settings):
            result = real_dispatch(action, active_settings)

            with dispatch_count.open("a", encoding="utf-8") as handle:
                handle.write("dispatch\\n")

            ready.write_text("ready", encoding="utf-8")

            # Hold execution after the side effect but before journal completion.
            while True:
                time.sleep(1)

        with (
            patch.object(loop, "ModelClient", return_value=FakeClient()),
            patch.object(loop, "_dispatch", side_effect=crash_after_dispatch),
        ):
            loop.run_task("Simulate process interruption", settings)
    """)

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(settings.workspace),
            str(settings.db),
            str(ready),
            str(dispatch_count),
        ],
        cwd=str(Path.cwd()),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + 20
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)

        if not ready.exists():
            if process.poll() is None:
                process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(
                "Child did not reach the post-dispatch crash point. "
                f"Exit={process.returncode}; stdout={stdout}; stderr={stderr}"
            )

        # Abrupt termination: bypass Python finally blocks and normal cleanup.
        process.terminate()
        process.communicate(timeout=5)

    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)

    # The external side effect happened before the process was terminated.
    assert target.read_text(encoding="utf-8") == (
        "write happened before process termination"
    )
    assert dispatch_count.read_text(encoding="utf-8").splitlines() == [
        "dispatch"
    ]

    db = sqlite3.connect(settings.db)
    try:
        interrupted = db.execute(
            """
            SELECT run_id, action_name, effect, status
            FROM action_executions
            WHERE action_name = 'write_file'
            """
        ).fetchone()
    finally:
        db.close()

    assert interrupted is not None
    assert interrupted[1:] == ("write_file", "write", "executing")

    # Restart NOVA. Its first operation is recovery; the model then finishes
    # the new task without requesting another write.
    outputs = [
        '{"action":"done","summary":"Recovery completed"}',
        '{"action":"read_file","path":"important.txt"}',
        '{"action":"done","summary":"Readback verified"}',
    ]

    def tracked_dispatch(action, active_settings):
        if action.get("action") == "write_file":
            with dispatch_count.open("a", encoding="utf-8") as handle:
                handle.write("dispatch\\n")
        return original_dispatch(action, active_settings)

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch(
            "nova.controller.loop._dispatch",
            side_effect=tracked_dispatch,
        ),
    ):
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task("Recover after interruption", settings)

    # Successful restart also proves the OS released the old runtime lock.
    assert result["agent_success"] is True
    assert result["recovered_actions"] == {
        "failed": 0,
        "uncertain": 1,
    }
    assert result["recovered_runs"] == 1

    db = sqlite3.connect(settings.db)
    try:
        status = db.execute(
            """
            SELECT status, write_verified_at, write_observed_sha256,
                   write_observed_length, write_verification_run_id
            FROM action_executions
            WHERE run_id = ? AND action_name = 'write_file'
            """,
            (interrupted[0],),
        ).fetchone()
    finally:
        db.close()

    expected_bytes = b"write happened before process termination"
    assert status[0] == "uncertain"
    assert status[1] is not None
    assert status[2] == hashlib.sha256(expected_bytes).hexdigest()
    assert status[3] == len(expected_bytes)
    assert status[4] is not None

    db = sqlite3.connect(settings.db)
    try:
        recovered_run = db.execute(
            """
            SELECT status, error_type, finished_at
            FROM runs
            WHERE id = ?
            """,
            (interrupted[0],),
        ).fetchone()
    finally:
        db.close()

    assert recovered_run is not None
    assert recovered_run[0:2] == ("interrupted", "ProcessInterrupted")
    assert recovered_run[2] is not None

    # Exactly one dispatch across both processes: recovery did not replay it.
    assert dispatch_count.read_text(encoding="utf-8").splitlines() == [
        "dispatch"
    ]
    assert target.read_text(encoding="utf-8") == (
        "write happened before process termination"
    )

def _run_uncertain_write_completion_case(tmp_path, outputs, tamper_content=None):
    import sqlite3

    settings = _settings(tmp_path)
    original_replace = file_ops.os.replace

    def replace_then_lose_confirmation(source, destination):
        original_replace(source, destination)

        if tamper_content is not None:
            from pathlib import Path
            Path(destination).write_text(tamper_content, encoding="utf-8")

        raise OSError("simulated lost confirmation")

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch.object(
            file_ops.os,
            "replace",
            side_effect=replace_then_lose_confirmation,
        ),
    ):
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task(
            "Create result.txt containing committed and verify it.",
            settings,
        )

    db = sqlite3.connect(settings.db)
    actions = db.execute(
        """
        SELECT action_name, status
        FROM action_executions
        WHERE run_id = ?
        ORDER BY step
        """,
        (result["run_id"],),
    ).fetchall()
    db.close()

    return settings, result, actions


def test_uncertain_write_followed_by_done_is_rejected(tmp_path):
    outputs = [
        '{"action":"write_file","path":"result.txt","content":"committed"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"done","summary":"Finished"}',
    ]

    settings, result, actions = _run_uncertain_write_completion_case(
        tmp_path, outputs
    )

    assert (settings.workspace / "result.txt").read_text() == "committed"
    assert result["agent_success"] is False
    assert result["completion_gate_blocked"] is True
    assert ("write_file", "uncertain") in actions
    assert result["stop_reason"] == "done_rejected"


def test_uncertain_write_exact_read_allows_completion(tmp_path):
    outputs = [
        '{"action":"write_file","path":"result.txt","content":"committed"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"read_file","path":"result.txt"}',
        '{"action":"done","summary":"Verified result.txt"}',
    ]

    settings, result, actions = _run_uncertain_write_completion_case(
        tmp_path, outputs
    )

    assert result["agent_success"] is True
    assert ("write_file", "uncertain") in actions
    assert ("read_file", "succeeded") in actions
    assert ("done", "succeeded") in actions
    assert (settings.workspace / "result.txt").read_text() == "committed"


def test_uncertain_write_incorrect_read_does_not_allow_completion(tmp_path):
    outputs = [
        '{"action":"write_file","path":"result.txt","content":"committed"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"read_file","path":"result.txt"}',
        '{"action":"done","summary":"Verified result.txt"}',
    ]

    _, result, actions = _run_uncertain_write_completion_case(
        tmp_path,
        outputs,
        tamper_content="tampered",
    )

    assert result["agent_success"] is False
    assert result["completion_gate_blocked"] is True
    assert ("write_file", "uncertain") in actions
    assert ("read_file", "succeeded") in actions
    assert result["stop_reason"] == "done_rejected"

def test_latest_same_path_uncertain_write_supersedes_older_after_readback(
    tmp_path,
):
    import sqlite3

    settings = _settings(tmp_path)
    original_replace = file_ops.os.replace
    replace_calls = 0

    def replace_then_lose_confirmation(source, destination):
        nonlocal replace_calls
        original_replace(source, destination)
        replace_calls += 1
        if replace_calls <= 2:
            raise OSError(f"simulated lost confirmation {replace_calls}")

    outputs = [
        '{"action":"write_file","path":"result.txt","content":"first version"}',
        '{"action":"write_file","path":"result.txt","content":"second version"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"read_file","path":"result.txt"}',
        '{"action":"done","summary":"Verified latest version"}',
    ]

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch.object(
            file_ops.os,
            "replace",
            side_effect=replace_then_lose_confirmation,
        ),
    ):
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()
        result = run_task("Write and verify the latest version", settings)

    assert result["agent_success"] is True
    assert (settings.workspace / "result.txt").read_text() == "second version"

    db = sqlite3.connect(settings.db)
    rows = db.execute(
        """
        SELECT execution_id, status, write_verified_at,
               write_superseded_at, write_superseded_by_execution_id
        FROM action_executions
        WHERE action_name = 'write_file'
        ORDER BY step
        """
    ).fetchall()
    db.close()

    assert len(rows) == 2
    older, newer = rows
    assert older[1] == "uncertain"
    assert older[2] is None
    assert older[3] is not None
    assert older[4] == newer[0]
    assert newer[1] == "uncertain"
    assert newer[2] is not None
    assert newer[3] is None
    assert newer[4] is None

def test_readback_of_older_version_does_not_clear_newer_uncertain_write(
    tmp_path,
):
    import sqlite3

    settings = _settings(tmp_path)
    original_replace = file_ops.os.replace
    replace_calls = 0

    def fail_second_replace(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            original_replace(source, destination)
        raise OSError(f"simulated uncertain write {replace_calls}")

    outputs = [
        '{"action":"write_file","path":"result.txt","content":"old version"}',
        '{"action":"write_file","path":"result.txt","content":"new version"}',
        '{"action":"done","summary":"Finished"}',
        '{"action":"read_file","path":"result.txt"}',
        '{"action":"done","summary":"Finished"}',
    ]

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch.object(
            file_ops.os,
            "replace",
            side_effect=fail_second_replace,
        ),
    ):
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()
        result = run_task("Verify the newest version", settings)

    assert result["agent_success"] is False
    assert result["completion_gate_blocked"] is True
    assert (settings.workspace / "result.txt").read_text() == "old version"

    db = sqlite3.connect(settings.db)
    rows = db.execute(
        """
        SELECT status, write_verified_at, write_superseded_at
        FROM action_executions
        WHERE action_name = 'write_file'
        ORDER BY step
        """
    ).fetchall()
    db.close()

    assert len(rows) == 2
    assert rows[0][0] == "uncertain"
    assert rows[0][1] is not None
    assert rows[0][2] is None
    assert rows[1] == ("uncertain", None, None)
