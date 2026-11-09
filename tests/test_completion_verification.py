import sqlite3
from unittest.mock import MagicMock, patch

from nova.config import Settings
from nova.controller.loop import run_task


def _settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "completion.db",
        max_steps=6,
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


def _run(tmp_path, outputs, verifier):
    settings = _settings(tmp_path)

    with patch("nova.controller.loop.ModelClient") as MockClient:
        client = MockClient.return_value
        client.chat_with_usage.side_effect = [
            (raw, _usage(), "success") for raw in outputs
        ]
        client.close = MagicMock()

        result = run_task(
            "Repair vault.py",
            settings,
            benchmark_task_id="hidden_auth",
            completion_verifier=verifier,
        )
        messages = [
            call.args[0]
            for call in client.chat_with_usage.call_args_list
        ]

    return settings, result, messages


def _journal(settings, run_id):
    with sqlite3.connect(settings.db) as db:
        return db.execute("""
            SELECT action_name, status, error_type
            FROM action_executions
            WHERE run_id = ?
            ORDER BY step
        """, (run_id,)).fetchall()


def test_done_is_accepted_when_verification_passes(tmp_path):
    outputs = [
        '{"action":"done","summary":"Task complete"}',
    ]

    verifier = MagicMock(return_value=True)
    settings, result, _ = _run(tmp_path, outputs, verifier)

    assert result["agent_success"] is True
    assert result["stop_reason"] == "completed"
    verifier.assert_called_once_with()

    assert _journal(settings, result["run_id"]) == [
        ("done", "succeeded", None),
    ]


def test_failed_verification_allows_repair_and_retry(tmp_path):
    outputs = [
        '{"action":"done","summary":"Task complete"}',
        '{"action":"write_file","path":"vault.py","content":"repaired"}',
        '{"action":"done","summary":"Task repaired"}',
    ]

    verifier = MagicMock(side_effect=[False, True])
    settings, result, messages = _run(tmp_path, outputs, verifier)

    assert result["agent_success"] is True
    assert result["stop_reason"] == "completed"
    assert verifier.call_count == 2

    assert _journal(settings, result["run_id"]) == [
        ("done", "failed", "CompletionVerificationFailed"),
        ("write_file", "succeeded", None),
        ("done", "succeeded", None),
    ]

    repair_messages = messages[1]
    feedback = [
        message["content"]
        for message in repair_messages
        if message["role"] == "user"
    ]

    assert any(
        "verification failed" in message.lower()
        and "try again" in message.lower()
        for message in feedback
    )


def test_repeated_verification_failure_stops_after_two_attempts(tmp_path):
    outputs = [
        '{"action":"done","summary":"First completion claim"}',
        '{"action":"done","summary":"Second completion claim"}',
    ]

    verifier = MagicMock(return_value=False)
    settings, result, _ = _run(tmp_path, outputs, verifier)

    assert result["agent_success"] is False
    assert result["stop_reason"] == "completion_verification_failed"
    assert verifier.call_count == 2

    assert _journal(settings, result["run_id"]) == [
        ("done", "failed", "CompletionVerificationFailed"),
        ("done", "failed", "CompletionVerificationFailed"),
    ]


def test_verifier_exception_fails_closed_and_closes_journal(tmp_path):
    outputs = [
        '{"action":"done","summary":"Task complete"}',
    ]

    verifier = MagicMock(
        side_effect=TimeoutError("private verifier output")
    )
    settings, result, messages = _run(tmp_path, outputs, verifier)

    assert result["agent_success"] is False
    assert result["stop_reason"] == "completion_verifier_error"
    verifier.assert_called_once_with()

    assert _journal(settings, result["run_id"]) == [
        ("done", "failed", "CompletionVerifierError"),
    ]

    with sqlite3.connect(settings.db) as db:
        row = db.execute(
            "SELECT actions FROM episodes WHERE run_id = ?",
            (result["run_id"],),
        ).fetchone()

    assert row is not None
    assert "private verifier output" not in row[0]
    assert "Completion verifier error." in row[0]

    assert all(
        "private verifier output" not in str(call)
        for call in messages
    )
