from unittest.mock import MagicMock, patch
import sqlite3

import pytest

from nova.config import Settings
from nova.controller.loop import (
    LOOP_GUARD_THRESHOLD,
    LOOP_GUARD_TOOL,
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