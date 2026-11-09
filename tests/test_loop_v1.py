import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from nova.config import Settings
from nova.controller.loop import (
    LOOP_GUARD_THRESHOLD,
    NOVA_ACTION_SCHEMA,
    NOVA_RESPONSE_FORMAT,
    _validate_action,
    run_task,
)

# =========================================================================
# Test helpers
# =========================================================================

def _make_settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "test.db",
        max_steps=8,
        temperature=0.2,
    )


def _fake_usage():
    return {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "usage_complete": True,
        "usage_json": "{}",
        "finish_reason": "stop",
    }


# =========================================================================
# Schema constants
# =========================================================================

def test_schema_allows_four_actions():
    assert NOVA_ACTION_SCHEMA["properties"]["action"]["enum"] == [
        "write_file", "read_file", "list_files", "done"
    ]
    assert NOVA_ACTION_SCHEMA["required"] == ["action"]
    assert NOVA_ACTION_SCHEMA["additionalProperties"] is False


def test_schema_is_sent_to_model(tmp_path):
    """When use_json_schema=True, the model call must include the schema."""
    settings = _make_settings(tmp_path)
    fake_done = '{"action": "done", "summary": "ok"}'

    with patch("nova.controller.loop.ModelClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.chat_with_usage.return_value = (
            fake_done, _fake_usage(), "success"
        )
        mock_client.close = MagicMock()

        run_task("test", settings, use_json_schema=True)

        # Inspect the kwargs the client was called with
        call_kwargs = mock_client.chat_with_usage.call_args.kwargs
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"] == NOVA_RESPONSE_FORMAT
        assert call_kwargs.get("reasoning_effort") == "none"


# =========================================================================
# Action validator
# =========================================================================

def test_validate_accepts_write_file():
    a = {"action": "write_file", "path": "a.py", "content": "x"}
    assert _validate_action(a) == a


def test_validate_accepts_read_file():
    a = {"action": "read_file", "path": "a.py"}
    assert _validate_action(a) == a


def test_validate_accepts_list_files():
    a = {"action": "list_files"}
    assert _validate_action(a) == a


def test_validate_accepts_done():
    a = {"action": "done", "summary": "ok"}
    assert _validate_action(a) == a


def test_validate_rejects_unknown_action():
    with pytest.raises(ValueError, match="Unknown or missing"):
        _validate_action({"action": "delete_file"})


def test_validate_rejects_missing_required_field():
    with pytest.raises(ValueError, match="Missing required"):
        _validate_action({"action": "write_file", "path": "a.py"})


def test_validate_rejects_unexpected_field():
    with pytest.raises(ValueError, match="Unexpected fields"):
        _validate_action({"action": "read_file", "path": "a.py", "content": "extra"})


def test_validate_rejects_non_string_field():
    with pytest.raises(ValueError, match="must be a string"):
        _validate_action({"action": "read_file", "path": 123})


def test_validate_rejects_non_dict():
    with pytest.raises(ValueError, match="must be a JSON object"):
        _validate_action(["not", "a", "dict"])


# =========================================================================
# Finding 7: controller guard
# =========================================================================

def test_guard_halts_after_three_list_files_failures(tmp_path):
    settings = _make_settings(tmp_path)
    fake_content = '{"action": "list_files"}'

    with patch("nova.controller.loop.ModelClient") as MockClient, \
         patch("nova.controller.loop._dispatch") as mock_dispatch:

        mock_client = MockClient.return_value
        mock_client.chat_with_usage.return_value = (
            fake_content, _fake_usage(), "success"
        )
        mock_client.close = MagicMock()

        mock_dispatch.side_effect = ValueError("path error")

        result = run_task("test task", settings, use_json_schema=False)

    assert result["stop_reason"] == "loop_detected"
    assert result["steps"] == LOOP_GUARD_THRESHOLD
    assert result["agent_success"] is False


def test_guard_allows_transient_failure_recovery(tmp_path):
    settings = _make_settings(tmp_path)
    fake_list = '{"action": "list_files"}'
    fake_done = '{"action": "done", "summary": "recovered"}'

    with patch("nova.controller.loop.ModelClient") as MockClient, \
         patch("nova.controller.loop._dispatch") as mock_dispatch:

        mock_client = MockClient.return_value
        mock_client.chat_with_usage.side_effect = [
            (fake_list, _fake_usage(), "success"),
            (fake_list, _fake_usage(), "success"),
            (fake_list, _fake_usage(), "success"),  # succeeds here
            (fake_done, _fake_usage(), "success"),
        ]
        mock_client.close = MagicMock()

        # Fail twice, then succeed on third call (transient pattern)
        mock_dispatch.side_effect = [
            ValueError("path error"),
            ValueError("path error"),
            "alpha.txt\nbeta.txt",
        ]

        result = run_task("test task", settings, use_json_schema=False)

    # Guard threshold is 3; two failures then a success resets the counter.
    assert result["stop_reason"] == "completed"
    assert result["agent_success"] is True


# =========================================================================
# Model error classification (must not be mislabeled as max_steps)
# =========================================================================

def test_model_error_is_recorded_in_database(tmp_path):
    """A failed model API call must record termination_reason='model_error'."""
    settings = _make_settings(tmp_path)
    usage = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "usage_complete": False,
        "usage_json": None,
        "finish_reason": None,
    }

    with patch("nova.controller.loop.ModelClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.chat_with_usage.return_value = (
            "",
            usage,
            "error: ConnectionError: Ollama unavailable",
        )
        mock_client.close = MagicMock()

        result = run_task("Test model failure", settings, use_json_schema=False)

    assert result["agent_success"] is False
    assert result["stop_reason"] == "model_error"
    assert result["usage_complete"] is False

    conn = sqlite3.connect(str(settings.db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT termination_reason FROM runs WHERE id = ?",
        (result["run_id"],),
    ).fetchone()
    conn.close()

    assert row is not None, "run was not written to database"
    assert row["termination_reason"] == "model_error"
def test_cross_tool_failures_trigger_guard_and_are_journaled(tmp_path):
    import json
    import sqlite3

    settings = _make_settings(tmp_path)
    outputs = [
        '{"action":"read_file","path":"a.py"}',
        '{"action":"write_file","path":"a.py","content":"x"}',
        '{"action":"list_files"}',
    ]

    with patch("nova.controller.loop.ModelClient") as MockClient, \
         patch("nova.controller.loop._dispatch") as mock_dispatch:

        mock_client = MockClient.return_value
        mock_client.chat_with_usage.side_effect = [
            (raw, _fake_usage(), "success") for raw in outputs
        ]
        mock_client.close = MagicMock()
        mock_dispatch.side_effect = [
            ValueError("shared synthetic failure"),
            ValueError("shared synthetic failure"),
            ValueError("shared synthetic failure"),
        ]

        result = run_task("cross-tool failure test", settings)

    assert result["stop_reason"] == "loop_detected"
    assert result["steps"] == 3
    assert mock_dispatch.call_count == 3

    conn = sqlite3.connect(settings.db)
    rows = conn.execute(
        """
        SELECT action_name, status, error_fingerprint
        FROM action_executions
        WHERE run_id = ?
        ORDER BY step
        """,
        (result["run_id"],),
    ).fetchall()

    assert [row[0] for row in rows] == [
        "read_file", "write_file", "list_files"
    ]
    assert [row[1] for row in rows] == [
        "failed", "uncertain", "failed"
    ]
    assert len({row[2] for row in rows}) == 1

    episode = conn.execute(
        "SELECT actions FROM episodes WHERE run_id = ?",
        (result["run_id"],),
    ).fetchone()
    transcript = json.loads(episode[0])
    assert [
        item["failure_occurrence_count"] for item in transcript
    ] == [1, 2, 3]
    assert transcript[-1]["guard_triggered"] is True

    run = conn.execute(
        "SELECT termination_reason FROM runs WHERE id = ?",
        (result["run_id"],),
    ).fetchone()
    assert run[0] == "loop_detected"
    conn.close()


def test_successful_retry_prevents_cross_tool_false_stop(tmp_path):
    import sqlite3

    settings = _make_settings(tmp_path)
    outputs = [
        '{"action":"read_file","path":"a.py"}',
        '{"action":"write_file","path":"a.py","content":"x"}',
        '{"action":"read_file","path":"a.py"}',
        '{"action":"list_files"}',
        '{"action":"done","summary":"recovered"}',
    ]

    with patch("nova.controller.loop.ModelClient") as MockClient, \
         patch("nova.controller.loop._dispatch") as mock_dispatch:

        mock_client = MockClient.return_value
        mock_client.chat_with_usage.side_effect = [
            (raw, _fake_usage(), "success") for raw in outputs
        ]
        mock_client.close = MagicMock()
        mock_dispatch.side_effect = [
            ValueError("shared synthetic failure"),
            ValueError("shared synthetic failure"),
            "file contents",
            ValueError("shared synthetic failure"),
        ]

        result = run_task("recovery test", settings)

    assert result["stop_reason"] == "completed"
    assert mock_dispatch.call_count == 4

    conn = sqlite3.connect(settings.db)
    rows = conn.execute(
        """
        SELECT action_name, status
        FROM action_executions
        WHERE run_id = ?
        ORDER BY step
        """,
        (result["run_id"],),
    ).fetchall()

    assert [row[1] for row in rows] == [
        "failed", "uncertain", "succeeded", "failed", "succeeded"
    ]
    conn.close()



def test_model_client_closes_when_database_connect_fails(tmp_path):
    settings = _make_settings(tmp_path)

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch(
            "nova.controller.loop.connect",
            side_effect=RuntimeError("database unavailable"),
        ),pytest.raises(RuntimeError, match="database unavailable")
    ):
        run_task("cleanup test", settings)

    MockClient.return_value.close.assert_called_once_with()


def test_resources_close_when_controller_execution_raises(tmp_path):
    from nova.memory.db import connect as db_connect

    settings = _make_settings(tmp_path)
    captured = {}

    def tracking_connect(db_path):
        captured["connection"] = db_connect(db_path)
        return captured["connection"]

    with (
        patch("nova.controller.loop.ModelClient") as MockClient,
        patch("nova.controller.loop.connect", side_effect=tracking_connect),
        patch(
            "nova.controller.loop._run_task_with_resources",
            side_effect=RuntimeError("injected controller failure"),
        ),pytest.raises(
        RuntimeError,
        match="injected controller failure",
    )
    ):
        run_task("cleanup test", settings)

    MockClient.return_value.close.assert_called_once_with()

    with pytest.raises(
        sqlite3.ProgrammingError,
        match="closed database",
    ):
        captured["connection"].execute("SELECT 1")

    audit = sqlite3.connect(settings.db)
    try:
        failed_run = audit.execute(
            """
            SELECT status, error_type, finished_at
            FROM runs
            """
        ).fetchone()
    finally:
        audit.close()

    assert failed_run is not None
    assert failed_run[0:2] == ("failed", "RuntimeError")
    assert failed_run[2] is not None
