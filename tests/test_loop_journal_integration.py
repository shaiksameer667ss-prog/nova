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

    outputs = ['{"action":"done","summary":"recovery complete"}']

    with patch("nova.controller.loop.ModelClient") as MockClient:
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task("Check journal recovery", settings)

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
    outputs = ['{"action":"done","summary":"Recovery completed"}']

    def tracked_dispatch(action, active_settings):
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
            SELECT status
            FROM action_executions
            WHERE run_id = ? AND action_name = 'write_file'
            """,
            (interrupted[0],),
        ).fetchone()
    finally:
        db.close()

    assert status == ("uncertain",)

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
