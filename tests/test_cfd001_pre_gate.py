"""Pre-gate tests for the CFD-001 acceptance-feedback loop.

Two layers:
  1. Unit: _cfd001_evaluate_candidate must distinguish correct from incorrect
     tokenizer implementations using the real task parser and the 11 cases.
  2. Integration: a failing pre-gate must append feedback to the model
     conversation and allow a retry, not dispatch a broken write.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from nova.config import Settings
from nova.controller.loop import (
    _CFD001_ACCEPTANCE_CASES,
    _cfd001_evaluate_candidate,
    _format_pre_gate_feedback,
    run_task,
)

# ---------------------------------------------------------------------------
# Real task parser (the stub in other tests returns list[str], not dict[str,str])
# ---------------------------------------------------------------------------

TASK_DIR = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "diagnostics"
    / "cross_file_dependency_001"
    / "repo"
)
PARSER_SRC = (TASK_DIR / "parser.py").read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Known candidate implementations
# ---------------------------------------------------------------------------

# V4 step-4: parity-aware. Passes all 11 cases. Extracted from episode DB.
GOOD_TOKENIZER = r'''def split_fields(source: str) -> list[str]:
    """Split a record at semicolons outside double-quoted values."""
    fields = []
    start = 0
    in_quotes = False

    i = 0
    while i < len(source):
        char = source[i]

        if char == '\\' and i + 1 < len(source):
            # Handle escape sequences: consume both characters without toggling quote state
            next_char = source[i + 1]
            i += 2
        elif char == '"':
            in_quotes = not in_quotes
            i += 1
        elif char == ";" and not in_quotes:
            fields.append(source[start:i].strip())
            start = i + 1
            i += 1
        else:
            i += 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields
'''

# V5 step-4: previous-character check, no parity handling. Fails 3 of 11
# (the three even-backslash cases). Extracted from episode DB.
BAD_TOKENIZER = r'''def split_fields(source: str) -> list[str]:
    """Split a record at semicolons outside double-quoted values."""
    fields = []
    start = 0
    in_quotes = False

    for index, char in enumerate(source):
        if char == '"':
            # Check for escaped quote: backslash before quote means it's not a delimiter
            if index > 0 and source[index - 1] == '\\':
                continue
            in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            fields.append(source[start:index].strip())
            start = index + 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields
'''

BROKEN_TOKENIZER = "def split_fields(source):\n    return [  # unterminated\n"


# ---------------------------------------------------------------------------
# Unit tests for _cfd001_evaluate_candidate
# ---------------------------------------------------------------------------

def test_evaluate_good_candidate_passes_all_11():
    result = _cfd001_evaluate_candidate(GOOD_TOKENIZER, PARSER_SRC)
    assert result["passed"] == 11, result
    assert result["failed"] == 0
    assert result["total"] == 11
    assert result["failures"] == []


def test_evaluate_bad_candidate_fails_the_three_even_backslash_cases():
    result = _cfd001_evaluate_candidate(BAD_TOKENIZER, PARSER_SRC)
    assert result["passed"] == 8, result
    assert result["failed"] == 3
    assert result["total"] == 11
    failure_names = {f["case"] for f in result["failures"]}
    assert failure_names == {
        "even_backslashes_before_closing_quote_2",
        "even_backslashes_before_closing_quote_4",
        "multiple_fields_with_even_backslashes",
    }
    # Each failure has structured fields
    for f in result["failures"]:
        assert set(f) == {"case", "input", "expected", "actual"}
        assert isinstance(f["input"], str)
        assert isinstance(f["expected"], str)
        assert isinstance(f["actual"], str)


def test_evaluate_syntactically_broken_candidate_returns_zero():
    result = _cfd001_evaluate_candidate(BROKEN_TOKENIZER, PARSER_SRC)
    assert result["passed"] == 0
    assert result["failed"] == 11
    assert result["total"] == 11
    assert any(f["case"] == "import_error" for f in result["failures"])


def test_format_pre_gate_feedback_is_concrete_and_non_prescriptive():
    result = _cfd001_evaluate_candidate(BAD_TOKENIZER, PARSER_SRC)
    feedback = _format_pre_gate_feedback(result)
    assert "3 of 11" in feedback
    assert "even_backslashes_before_closing_quote_2" in feedback
    assert "Expected:" in feedback
    assert "Actual:" in feedback
    # Must NOT prescribe an algorithm
    assert "parity" not in feedback.lower()
    assert "state machine" not in feedback.lower()
    assert "consume" not in feedback.lower()


def test_cases_constant_has_11_entries():
    assert len(_CFD001_ACCEPTANCE_CASES) == 11


# ---------------------------------------------------------------------------
# Integration: pre-gate blocks bad candidate, feeds back, lets model retry
# ---------------------------------------------------------------------------

def _make_settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "parser.py").write_text(PARSER_SRC, encoding="utf-8")
    (workspace / "tokenizer.py").write_text(
        "def split_fields(source):\n    return source.split(';')\n",
        encoding="utf-8",
    )
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "test.db",
        max_steps=10,
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


def _plan_response():
    return json.dumps({
        "objective": "Fix tokenizer",
        "steps": ["Read parser.py", "Read tokenizer.py", "Fix tokenizer.py"],
        "success_criteria": ["parse_record returns correct dict"],
        "risks": [],
        "change_summary": "Initial plan",
    })


def _read_action(path):
    return json.dumps({"action": "read_file", "path": path})


def _write_action(path, content):
    return json.dumps({"action": "write_file", "path": path, "content": content})


def _done_action(summary):
    return json.dumps({"action": "done", "summary": summary})


def test_pre_gate_fail_then_pass_feeds_feedback_and_proceeds(tmp_path):
    """Model proposes bad tokenizer → pre-gate blocks, feedback appended.
    Model sees feedback, proposes good tokenizer → pre-gate passes, run continues."""
    settings = _make_settings(tmp_path)

    # Stateful fake evaluator: first call → fail (3 cases), second call → pass
    eval_calls = []

    def fake_eval(tokenizer_source, parser_source):
        eval_calls.append(tokenizer_source[:40])
        if len(eval_calls) == 1:
            return {
                "passed": 8, "failed": 3, "total": 11,
                "failures": [
                    {"case": "even_backslashes_before_closing_quote_2",
                     "input": "path=\"C:\\\\\";status=ok",
                     "expected": "{'path': 'C:\\\\', 'status': 'ok'}",
                     "actual": "ValueError('Unterminated quoted value')"},
                    {"case": "even_backslashes_before_closing_quote_4",
                     "input": "path=\"C:\\\\\\\\\";status=ok",
                     "expected": "{'path': 'C:\\\\\\\\', 'status': 'ok'}",
                     "actual": "ValueError('Unterminated quoted value')"},
                    {"case": "multiple_fields_with_even_backslashes",
                     "input": "p=\"x\\\\\";q=\"y\\\\\\\\\";r=z",
                     "expected": "{'p': 'x\\\\', 'q': 'y\\\\\\\\', 'r': 'z'}",
                     "actual": "ValueError(\"Invalid quoted value for 'p'\")"},
                ],
            }
        return {"passed": 11, "failed": 0, "total": 11, "failures": []}

    # Model responses: plan, read parser, write bad, write good, done
    model_outputs = [
        ("planning", _plan_response()),
        ("agent_step", _read_action("parser.py")),
        ("agent_step", _write_action("tokenizer.py", "BAD_CONTENT")),
        ("agent_step", _write_action("tokenizer.py", "GOOD_CONTENT")),
        ("agent_step", _done_action("done")),
    ]

    # Mock model client returning these in order
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0
        def chat_with_usage(self, messages, **kwargs):
            if self.calls >= len(model_outputs):
                return "", _fake_usage(), "error: exhausted"
            _purpose, raw = model_outputs[self.calls]
            self.calls += 1
            return raw, _fake_usage(), "success"
        def close(self):
            pass

    # Mock dispatch: read returns parser content, write succeeds and updates observed
    def fake_dispatch(action, settings_obj):
        if action["action"] == "read_file":
            return (settings_obj.workspace / action["path"]).read_text(encoding="utf-8")
        if action["action"] == "write_file":
            (settings_obj.workspace / action["path"]).write_text(action["content"], encoding="utf-8")
            return "write succeeded"
        raise AssertionError(f"unexpected dispatch: {action}")

    # Mock review to APPROVE (we are testing pre-gate wiring, not reviewer)
    def fake_review(*args, **kwargs):
        return {"decision": "APPROVE", "root_cause": "x", "causal_chain": [],
                "evidence": [{"path": "tokenizer.py", "start_line": 1, "end_line": 2}],
                "repair_target": "tokenizer.py", "guidance": ""}

    # The repair-task gate only runs on 'done', needs postwrite probes; bypass that
    # by mocking completion verification
    with patch("nova.controller.loop.ModelClient", FakeClient), \
         patch("nova.controller.loop._dispatch", side_effect=fake_dispatch), \
         patch("nova.controller.loop._cfd001_evaluate_candidate", side_effect=fake_eval), \
         patch("nova.controller.loop.parse_prewrite_review", return_value=fake_review()), \
         patch("nova.tools.behavioral_probe.run_behavioral_probe",
               return_value={"verdict": "PREDICTION_MATCHED", "probe_completed": True,
                             "evidence_kind": "sandbox_execution", "causality_established": False}):

        result = run_task(
            "Fix escaped quoted-value parsing.",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    # Pre-gate was consulted for both writes
    assert len(eval_calls) == 2, eval_calls
    # Counter reset: not blocked by pre-gate
    assert result.get("pre_gate_blocked") is not True, result
    with sqlite3.connect(settings.db) as conn:
        row = conn.execute(
            "SELECT actions FROM episodes WHERE run_id=?",
            (result["run_id"],),
        ).fetchone()
    assert row is not None
    actions = json.loads(row[0])
    pre_gate_statuses = [
        item.get("execution_status")
        for item in actions
        if item.get("execution_status") in
           ("blocked_by_pre_gate_acceptance", "blocked_by_pre_gate_limit")
    ]
    assert "blocked_by_pre_gate_acceptance" in pre_gate_statuses


def test_pre_gate_blocks_after_max_iterations(tmp_path):
    """Model proposes bad candidates 3 times → pre-gate blocks with pre_gate_blocked."""
    settings = _make_settings(tmp_path)

    def always_fail(tokenizer_source, parser_source):
        return {
            "passed": 8, "failed": 3, "total": 11,
            "failures": [
                {"case": f"case_{i}", "input": "x", "expected": "y", "actual": "z"}
                for i in range(3)
            ],
        }

    # plan, read parser, bad write, bad write, bad write (3 failures), then no more
    model_outputs = [
        ("planning", _plan_response()),
        ("agent_step", _read_action("parser.py")),
        ("agent_step", _write_action("tokenizer.py", "BAD_1")),
        ("agent_step", _write_action("tokenizer.py", "BAD_2")),
        ("agent_step", _write_action("tokenizer.py", "BAD_3")),
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0
        def chat_with_usage(self, messages, **kwargs):
            if self.calls >= len(model_outputs):
                return "", _fake_usage(), "error: exhausted"
            _purpose, raw = model_outputs[self.calls]
            self.calls += 1
            return raw, _fake_usage(), "success"
        def close(self):
            pass

    def fake_dispatch(action, settings_obj):
        if action["action"] == "read_file":
            return (settings_obj.workspace / action["path"]).read_text(encoding="utf-8")
        raise AssertionError(f"write should not dispatch; got {action}")

    with patch("nova.controller.loop.ModelClient", FakeClient), \
         patch("nova.controller.loop._dispatch", side_effect=fake_dispatch), \
         patch("nova.controller.loop._cfd001_evaluate_candidate", side_effect=always_fail):

        result = run_task(
            "Fix escaped quoted-value parsing.",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    assert result["pre_gate_blocked"] is True, result
    assert result["stop_reason"] == "pre_gate_blocked", result
