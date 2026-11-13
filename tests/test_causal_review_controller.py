import ast
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nova.config import Settings
from nova.controller.loop import run_task

PARSER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "eval" / "diagnostics" / "cross_file_dependency_001" / "repo" / "parser.py"
).read_text(encoding="utf-8-sig")
TOKENIZER_SOURCE = (
    "def split_fields(source):\n"
    "    return source.split(';')\n"
)


@pytest.fixture(autouse=True)
def _bypass_pre_gate(monkeypatch):
    """Existing tests predate the CFD-001 pre-gate. Bypass it by default
    so downstream behavior (dependency target, probe contract, review)
    is exercised as designed. Dedicated pre-gate tests live in
    tests/test_cfd001_pre_gate.py with real evaluator behavior."""
    monkeypatch.setattr(
        "nova.controller.loop._cfd001_evaluate_candidate",
        lambda tokenizer_source, parser_source: {
            "passed": 11,
            "failed": 0,
            "total": 11,
            "failures": [],
        },
    )


@pytest.fixture(autouse=True)
def stub_behavioral_probe(monkeypatch):
    def fake_probe(observed_files, probe):
        return {
            "verdict": "PREDICTION_MATCHED",
            "probe_kind": "function_call",
            "path": probe["path"],
            "function": probe["function"],
            "prediction_matched": True,
            "probe_completed": True,
            "evidence_kind": "sandbox_execution",
            "causality_established": False,
        }

    monkeypatch.setattr(
        "nova.tools.behavioral_probe.run_behavioral_probe",
        fake_probe,
    )


def make_settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "parser.py").write_text(PARSER_SOURCE, encoding="utf-8")
    (workspace / "tokenizer.py").write_text(TOKENIZER_SOURCE, encoding="utf-8")
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "test.db",
        max_steps=10,
        temperature=0.2,
    )


def usage():
    return {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "usage_complete": True,
        "usage_json": "{}",
        "finish_reason": "stop",
    }


def plan():
    return json.dumps({
        "objective": "Correct the parser behavior.",
        "steps": [
            "Inspect the parser and its dependencies.",
            "Repair the component responsible for the defect.",
            "Verify the resulting behavior.",
        ],
        "success_criteria": ["The parser follows its contract."],
        "risks": ["A repair could affect other parser behavior."],
        "change_summary": "Initial plan",
    })


def action(name, **fields):
    return json.dumps({"action": name, **fields})


def review(
    decision,
    *,
    evidence=None,
    repair_target="",
    guidance="Use the source evidence to select the correct repair.",
):
    return json.dumps({
        "decision": decision,
        "root_cause": "The tokenizer does not handle quoted delimiters correctly.",
        "causal_chain": [
            "The parser imports split_fields from the tokenizer.",
            "The tokenizer separates fields before the parser interprets values.",
        ],
        "evidence": evidence or [],
        "repair_target": repair_target,
        "guidance": guidance,
    })


def install_model(responses, hypothesis_response=None):
    client = MagicMock()
    remaining = iter(responses)
    hypothesis_responses = (
        iter(hypothesis_response)
        if isinstance(hypothesis_response, list)
        else None
    )

    def respond(*args, **kwargs):
        schema = kwargs.get("response_format", {}).get("json_schema", {})
        if schema.get("name") == "nova_hypothesis":
            payload = json.loads(args[0][-1]["content"])
            candidates = []
            for item in payload["observed_sources"]:
                tree = ast.parse(item["source"], filename=item["path"])
                functions = {
                    node.name
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                }
                if "split_fields" in functions:
                    candidates.append((
                        item["path"],
                        "split_fields",
                        ["left=one;right=two"],
                        ["left=one", "right=two"],
                    ))
                if "parse_record" in functions:
                    candidates.append((
                        item["path"],
                        "parse_record",
                        ["left=one;right=two"],
                        {"left": "one", "right": "two"},
                    ))

            if hypothesis_response is not None:
                hypothesis = (
                    next(hypothesis_responses)
                    if hypothesis_responses is not None
                    else hypothesis_response
                )
            else:
                if not candidates:
                    raise AssertionError(
                        "No supported function found in observed test sources."
                    )
                path, function, args, expected = next(
                    (candidate for candidate in candidates
                     if candidate[1] == "split_fields"),
                    candidates[0],
                )
                hypothesis = {
                    "hypothesis": "The observed function returns the expected fields.",
                    "prediction": "A simple record is parsed into two fields.",
                    "probe": {
                        "kind": "function_call",
                        "path": path,
                        "function": function,
                        "symbol": "",
                        "expected_present": False,
                        "args": args,
                        "kwargs": {},
                        "expected_result": expected,
                    },
                }
            return json.dumps(hypothesis), usage(), "success"
        return next(remaining), usage(), "success"

    client.chat_with_usage.side_effect = respond
    client.close = MagicMock()
    return client


def read_episode(settings):
    with sqlite3.connect(settings.db) as conn:
        row = conn.execute("SELECT actions FROM episodes").fetchone()
    return json.loads(row[0])


def test_approved_existing_file_write_is_dispatched_and_recorded(tmp_path):
    settings = make_settings(tmp_path)
    approved = review(
        "APPROVE",
        evidence=[{"path": "parser.py", "start_line": 1, "end_line": 1}],
        repair_target="parser.py",
    )
    client = install_model([
        plan(),
        action("read_file", path="parser.py"),
        action("write_file", path="parser.py", content="# reviewed fix\n"),
        approved,
        action("done", summary="Completed after approved repair."),
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            return PARSER_SOURCE
        return "write succeeded"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Correct the parser", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["causal_reviews"] == 1
    assert result["causal_review_blocked"] is False
    assert [item["action"] for item in dispatches] == ["read_file", "write_file"]

    review_schema = client.chat_with_usage.call_args_list[4].kwargs[
        "response_format"
    ]["json_schema"]["schema"]
    assert review_schema["properties"]["evidence"]["items"]["properties"][
        "path"
    ]["enum"] == ["parser.py", "tokenizer.py"]

    write_event = next(
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    )
    assert write_event["causal_review"]["decision"] == "APPROVE"
    assert write_event["execution_status"] == "succeeded"


def test_rejected_write_is_not_dispatched_and_agent_receives_guidance(tmp_path):
    settings = make_settings(tmp_path)
    rejected = review(
        "REVISE",
        evidence=[{"path": "tokenizer.py", "start_line": 1, "end_line": 2}],
        repair_target="tokenizer.py",
        guidance="Inspect and repair the tokenizer dependency instead.",
    )
    client = install_model([
        plan(),
        action("read_file", path="parser.py"),
        action("write_file", path="parser.py", content="# wrong target\n"),
        rejected,
        action("read_file", path="tokenizer.py"),
        action("done", summary="Inspected the dependency."),
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["path"] == "parser.py":
            return PARSER_SOURCE
        return TOKENIZER_SOURCE

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Correct the parser", settings, planning_mode=True)

    assert result["causal_reviews"] == 1
    assert [item["action"] for item in dispatches] == ["read_file", "read_file"]

    write_event = next(
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    )
    assert write_event["execution_status"] == "blocked_by_causal_review"
    assert write_event["causal_review"]["decision"] == "REVISE"


def test_investigate_prompts_dependency_read_before_repair(tmp_path):
    settings = make_settings(tmp_path)
    investigate = review(
        "INVESTIGATE",
        evidence=[{"path": "parser.py", "start_line": 1, "end_line": 1}],
        guidance="Inspect the imported tokenizer before selecting a repair target.",
    )
    approved = review(
        "APPROVE",
        evidence=[{"path": "tokenizer.py", "start_line": 1, "end_line": 2}],
        repair_target="tokenizer.py",
    )
    client = install_model([
        plan(),
        action("read_file", path="parser.py"),
        action("write_file", path="parser.py", content="# initial proposal\n"),
        investigate,
        action("read_file", path="tokenizer.py"),
        action("write_file", path="tokenizer.py", content="# repaired tokenizer\n"),
        approved,
        action("done", summary="Repaired the tokenizer."),
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file" and candidate["path"] == "parser.py":
            return PARSER_SOURCE
        if candidate["action"] == "read_file":
            return TOKENIZER_SOURCE
        return "write succeeded"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Correct the parser", settings, planning_mode=True)

    assert result["causal_reviews"] == 2
    assert result["causal_review_blocked"] is False
    assert [
        (item["action"], item.get("path")) for item in dispatches
    ] == [
        ("read_file", "parser.py"),
        ("read_file", "tokenizer.py"),
        ("write_file", "tokenizer.py"),
    ]


def test_invalid_causal_review_blocks_existing_file_write(tmp_path):
    settings = make_settings(tmp_path)
    client = install_model([
        plan(),
        action("read_file", path="parser.py"),
        action("write_file", path="parser.py", content="# unreviewed\n"),
        "not valid review JSON",
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        return PARSER_SOURCE

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Correct the parser", settings, planning_mode=True)

    assert result["agent_success"] is False
    assert result["stop_reason"] == "causal_review_blocked"
    assert result["causal_review_blocked"] is True
    assert [item["action"] for item in dispatches] == ["read_file"]

    write_event = next(
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    )
    assert write_event["execution_status"] == "blocked_by_causal_review"
    assert "invalid_causal_review" in write_event["causal_review_error"]


def test_new_file_creation_does_not_trigger_causal_review(tmp_path):
    settings = make_settings(tmp_path)
    client = install_model([
        plan(),
        action("write_file", path="new_module.py", content="VALUE = 1\n"),
        action("done", summary="Created a new module."),
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        return "write succeeded"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Create a new module", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["causal_reviews"] == 0
    assert [item["action"] for item in dispatches] == ["write_file"]

    with sqlite3.connect(settings.db) as conn:
        purposes = [
            row[0] for row in conn.execute(
                "SELECT purpose FROM model_calls ORDER BY rowid"
            )
        ]
    assert "hypothesis_generation" not in purposes
    assert "causal_review" not in purposes


def test_scaffolding_only_repair_cannot_complete(tmp_path):
    settings = make_settings(tmp_path)
    client = install_model([
        plan(),
        action("write_file", path="probe.py", content="print('not executed')\n"),
        action("done", summary="I created a probe."),
        action("done", summary="I still have not repaired the tokenizer."),
    ])
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "write_file":
            (active_settings.workspace / candidate["path"]).write_text(
                candidate["content"], encoding="utf-8"
            )
        return "write succeeded"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task(
            "Fix the parser bug by testing the tokenizer.",
            settings,
            planning_mode=True,
        )

    assert result["agent_success"] is False
    assert result["stop_reason"] == "done_rejected"
    assert result["done_rejections"] == 2
    assert result["completion_gate_blocked"] is True
    assert result["new_files"] == ["probe.py"]
    assert result["changed_source_files"] == []
    assert [item["action"] for item in dispatches] == ["write_file"]

def test_behavioral_hypothesis_runs_and_reaches_causal_review(tmp_path):
    from nova.controller import loop as loop_module

    settings = make_settings(tmp_path)
    runtime_input = r'name="A \"quoted; value\"";status=ok'
    baseline_exception = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }

    parser_source = (
        "import ast\n\n"
        "from tokenizer import split_fields\n\n\n"
        "def parse_record(source: str) -> dict[str, str]:\n"
        "    if not isinstance(source, str):\n"
        "        raise TypeError(\"source must be a string\")\n"
        "    if not source.strip():\n"
        "        return {}\n"
        "    result = {}\n"
        "    for field in split_fields(source):\n"
        "        if not field:\n"
        "            continue\n"
        "        key, separator, raw_value = field.partition(\"=\")\n"
        "        key = key.strip()\n"
        "        if not separator or not key:\n"
        "            raise ValueError(f\"Invalid field: {field!r}\")\n"
        "        raw_value = raw_value.strip()\n"
        "        if raw_value.startswith('\"'):\n"
        "            try:\n"
        "                value = ast.literal_eval(raw_value)\n"
        "            except (SyntaxError, ValueError) as exc:\n"
        "                raise ValueError(\n"
        "                    f\"Invalid quoted value for {key!r}\"\n"
        "                ) from exc\n"
        "            if not isinstance(value, str):\n"
        "                raise ValueError(f\"Expected a string value for {key!r}\")\n"
        "        else:\n"
        "            value = raw_value\n"
        "        result[key] = value\n"
        "    return result\n"
    )
    (settings.workspace / "parser.py").write_text(
        parser_source,
        encoding="utf-8",
    )

    fixed_tokenizer = r"""
def split_fields(source: str) -> list[str]:
    fields = []
    start = 0
    in_quotes = False
    escaped = False

    for index, char in enumerate(source):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            fields.append(source[start:index].strip())
            start = index + 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields
""".lstrip("\n")

    approved = review(
        "APPROVE",
        evidence=[{
            "path": "tokenizer.py",
            "start_line": 1,
            "end_line": 2,
        }],
        repair_target="tokenizer.py",
    )

    hypothesis = {
        "hypothesis": (
            "The tokenizer treats escaped quotes as delimiters and splits "
            "inside the quoted value."
        ),
        "prediction": (
            "The unchanged tokenizer raises an unterminated-quote error."
        ),
        "probe": {
            "kind": "function_call",
            "path": "tokenizer.py",
            "function": "split_fields",
            "symbol": "",
            "expected_present": False,
            "args": [runtime_input],
            "kwargs": {},
            "expected_result": None,
            "expected_exception": baseline_exception,
        },
    }
    wrong_hypothesis = {
        **hypothesis,
        "probe": {
            **hypothesis["probe"],
            "path": "parser.py",
            "function": "parse_record",
        },
    }

    client = install_model(
        [
            plan(),
            action("read_file", path="parser.py"),
            action("write_file", path="tokenizer.py", content=fixed_tokenizer),
            action("write_file", path="tokenizer.py", content=fixed_tokenizer),
            approved,
            action("done", summary="Tokenizer repaired and behavior verified."),
        ],
        hypothesis_response=[wrong_hypothesis, hypothesis],
    )
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            return (
                parser_source
                if candidate["path"] == "parser.py"
                else TOKENIZER_SOURCE
            )
        if candidate["action"] == "write_file":
            (active_settings.workspace / candidate["path"]).write_text(
                candidate["content"], encoding="utf-8"
            )
            return "write succeeded"
        raise AssertionError(f"Unexpected action: {candidate['action']}")

    prewrite_result = {
        "verdict": "PREDICTION_MISMATCHED",
        "probe_kind": "function_call",
        "path": "tokenizer.py",
        "function": "split_fields",
        "expected_result": None,
        "expected_exception": baseline_exception,
        "actual_result": [
            'name="A \\"quoted',
            'value\\""',
            "status=ok",
        ],
        "prediction_matched": False,
        "probe_completed": True,
        "evidence_kind": "sandbox_execution",
        "causality_established": False,
    }

    acceptance_probes = loop_module._cfd001_postwrite_acceptance_probes()
    postwrite_results = []

    for probe_spec in acceptance_probes:
        result = {
            "verdict": "PREDICTION_MATCHED",
            "probe_kind": "function_call",
            "path": "parser.py",
            "function": "parse_record",
            "expected_result": probe_spec["expected_result"],
            "expected_exception": probe_spec["expected_exception"],
            "prediction_matched": True,
            "probe_completed": True,
            "evidence_kind": "sandbox_execution",
            "causality_established": False,
        }
        if probe_spec["expected_exception"] is None:
            result["actual_result"] = probe_spec["expected_result"]
        else:
            result["actual_exception"] = probe_spec["expected_exception"]
        postwrite_results.append(result)

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
        patch(
            "nova.tools.behavioral_probe.run_behavioral_probe",
            side_effect=[prewrite_result, *postwrite_results],
        ) as probe_runner,
        patch(
            "nova.controller.loop.build_prewrite_review_messages",
            wraps=loop_module.build_prewrite_review_messages,
        ) as review_builder,
    ):
        result = run_task(
            "Fix the parser bug",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    assert result["agent_success"] is True, result
    assert [item["action"] for item in dispatches] == ["read_file", "write_file"]
    assert result["causal_reviews"] == 1
    assert result["dependency_target_blocked"] is False
    assert result["probes_attempted"] == 1 + len(acceptance_probes)
    assert result["probes_completed"] == 1 + len(acceptance_probes)
    assert result["changed_source_files"] == ["tokenizer.py"]
    assert result["postwrite_behavior_check_passed"] is True
    assert probe_runner.call_count == 1 + len(acceptance_probes)

    write_events = [
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    ]
    assert len(write_events) == 2
    assert write_events[0]["execution_status"] == "blocked_by_dependency_target"
    assert write_events[0]["rejected_dependency_probe"] == {
        "path": "parser.py", "function": "parse_record"
    }
    assert write_events[0]["required_dependency_probe"] == {
        "path": "tokenizer.py", "function": "split_fields"
    }
    assert write_events[1]["execution_status"] == "succeeded"

    observed_files, submitted_probe = probe_runner.call_args_list[0].args
    assert observed_files["tokenizer.py"] == TOKENIZER_SOURCE
    assert submitted_probe["path"] == "tokenizer.py"
    assert submitted_probe["function"] == "split_fields"
    assert submitted_probe["args"] == [runtime_input]
    assert submitted_probe["expected_exception"] == baseline_exception
    assert submitted_probe["expected_result"] is None

    for call, acceptance_probe in zip(
        probe_runner.call_args_list[1:],
        acceptance_probes,
        strict=True,
    ):
        postwrite_files, postwrite_probe = call.args
        assert postwrite_files["tokenizer.py"] == fixed_tokenizer
        assert postwrite_files["parser.py"] == parser_source
        assert postwrite_probe == acceptance_probe
        assert postwrite_probe["path"] == "parser.py"
        assert postwrite_probe["function"] == "parse_record"

    assert result["completion_gate"] == "postwrite_task_contract"

    review_context = review_builder.call_args.args[1]
    assert review_context["hypothesis_test"]["probe_result"] == prewrite_result
    assert review_context["hypothesis_test"]["verdict"] == "PREDICTION_MISMATCHED"
    assert (
        review_context["hypothesis_test"]["probe"]["expected_exception"]
        == baseline_exception
    )
    assert review_context["hypothesis_test"]["causality_established"] is False

def test_dependency_target_limit_blocks_after_two_rejections(tmp_path):
    settings = make_settings(tmp_path)
    runtime_input = 'name="A; B";status=ok'
    expected = ['name="A; B"', "status=ok"]

    wrong_hypothesis = {
        "hypothesis": "The caller parser is responsible for the delimiter behavior.",
        "prediction": "parse_record returns the expected two fields.",
        "probe": {
            "kind": "function_call",
            "path": "parser.py",
            "function": "parse_record",
            "symbol": "",
            "expected_present": False,
            "args": [runtime_input],
            "kwargs": {},
            "expected_result": expected,
        },
    }

    client = install_model(
        [
            plan(),
            action("read_file", path="parser.py"),
            action("write_file", path="tokenizer.py", content="# first blocked proposal\n"),
            action("write_file", path="tokenizer.py", content="# second blocked proposal\n"),
        ],
        hypothesis_response=[wrong_hypothesis, wrong_hypothesis],
    )
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            return PARSER_SOURCE
        raise AssertionError(
            f"Rejected write must not be dispatched: {candidate}"
        )

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
        patch(
            "nova.tools.behavioral_probe.run_behavioral_probe",
            side_effect=AssertionError(
                "A dependency-target rejection must not execute a sandbox probe."
            ),
        ) as probe_runner,
        patch(
            "nova.controller.loop.build_prewrite_review_messages",
            side_effect=AssertionError(
                "A dependency-target rejection must not reach causal review."
            ),
        ) as review_builder,
    ):
        result = run_task(
            "Fix the parser bug",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    assert result["agent_success"] is False
    assert result["stop_reason"] == "dependency_target_blocked"
    assert result["dependency_target_blocked"] is True
    assert result["consecutive_dependency_target_rejections"] == 2
    assert result["causal_reviews"] == 0
    assert result["probes_attempted"] == 0
    assert result["probes_completed"] == 0
    assert result["changed_source_files"] == []
    assert [item["action"] for item in dispatches] == ["read_file"]
    probe_runner.assert_not_called()
    review_builder.assert_not_called()

    write_events = [
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    ]
    assert len(write_events) == 2
    assert write_events[0]["execution_status"] == "blocked_by_dependency_target"
    assert write_events[1]["execution_status"] == "blocked_by_dependency_target_limit"



def test_required_dependency_probe_target_normalizes_windows_path():
    from nova.controller.hypothesis_testing import required_dependency_probe_target

    observed = {"parser.py": PARSER_SOURCE, "tokenizer.py": TOKENIZER_SOURCE}
    expected = {"path": "tokenizer.py", "function": "split_fields"}

    assert required_dependency_probe_target(observed, "parser.py") == expected
    assert required_dependency_probe_target(observed, "tokenizer.py") == expected
    assert required_dependency_probe_target(observed, r".\tokenizer.py") == expected
    assert required_dependency_probe_target(observed, "unrelated.py") is None

def test_invalid_python_write_is_rejected_before_causal_review(tmp_path):
    settings = make_settings(tmp_path)
    settings.max_steps = 3

    client = install_model([
        plan(),
        action("read_file", path="parser.py"),
        action(
            "write_file",
            path="tokenizer.py",
            content=(
                "def split_fields(source):\n"
                "fields = []\n"
                "    return fields\n"
            ),
        ),
        action("read_file", path="tokenizer.py"),
    ])

    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            if candidate["path"] == "parser.py":
                return PARSER_SOURCE
            if candidate["path"] == "tokenizer.py":
                return TOKENIZER_SOURCE
        raise AssertionError(f"Unexpected dispatched action: {candidate}")

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
        patch(
            "nova.controller.loop.build_hypothesis_messages",
            side_effect=AssertionError(
                "Hypothesis generation must not run for invalid Python."
            ),
        ) as hypothesis_builder,
        patch(
            "nova.controller.loop.build_prewrite_review_messages",
            side_effect=AssertionError(
                "Causal review must not run for invalid Python."
            ),
        ) as review_builder,
    ):
        result = run_task(
            "Repair the tokenizer implementation.",
            settings,
            planning_mode=True,
        )

    assert result["causal_reviews"] == 0
    assert result["probes_attempted"] == 0
    assert result["changed_source_files"] == []
    assert [item["action"] for item in dispatches] == [
        "read_file",
        "read_file",
    ]

    write_event = next(
        item
        for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    )
    assert write_event["execution_status"] == "blocked_by_syntax_validation"
    assert "expected an indented block" in (
        write_event["syntax_validation_error"].lower()
    )

    hypothesis_builder.assert_not_called()
    review_builder.assert_not_called()
def test_cfd001_invalid_probe_retries_without_consuming_review_or_probe_counts(
    tmp_path,
):
    from nova.controller import loop as loop_module
    from nova.controller.hypothesis_testing import ProbeContractError
    from nova.tools import behavioral_probe as behavioral_probe_module

    settings = make_settings(tmp_path)

    runtime_input = r'label="A \"quoted; phrase\"";owner=Ops'
    expected = [r'label="A \"quoted; phrase\""', "owner=Ops"]

    fixed_tokenizer = r"""def split_fields(source: str) -> list[str]:
    fields = []
    start = 0
    in_quotes = False
    backslashes = 0

    for index, char in enumerate(source):
        if char == "\\":
            backslashes += 1
            continue

        escaped = backslashes % 2 == 1
        backslashes = 0

        if char == '"':
            if not escaped:
                in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            fields.append(source[start:index].strip())
            start = index + 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields
"""

    hypothesis = {
        "hypothesis": "The tokenizer mishandles escaped quotes in quoted fields.",
        "prediction": "The tokenizer preserves the embedded semicolon.",
        "probe": {
            "kind": "function_call",
            "path": "tokenizer.py",
            "function": "split_fields",
            "symbol": "",
            "expected_present": False,
            "args": [runtime_input],
            "kwargs": {},
            "expected_result": expected,
        },
    }

    approved = review(
        "APPROVE",
        evidence=[{
            "path": "tokenizer.py",
            "start_line": 1,
            "end_line": 2,
        }],
        repair_target="tokenizer.py",
    )

    client = install_model(
        [
            plan(),
            action("read_file", path="parser.py"),
            action("write_file", path="tokenizer.py", content=fixed_tokenizer),
            action("write_file", path="tokenizer.py", content=fixed_tokenizer),
            approved,
            action("done", summary="Tokenizer repaired and behavior verified."),
        ],
        hypothesis_response=hypothesis,
    )

    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            if candidate["path"] == "parser.py":
                return PARSER_SOURCE
            if candidate["path"] == "tokenizer.py":
                return TOKENIZER_SOURCE
        elif candidate["action"] == "write_file":
            (active_settings.workspace / candidate["path"]).write_text(
                candidate["content"],
                encoding="utf-8",
            )
            return "write succeeded"
        raise AssertionError(f"Unexpected action: {candidate}")

    original_parse = loop_module.parse_hypothesis
    parse_calls = []

    def reject_first_probe_then_parse(raw, observed_files, benchmark_task_id=None):
        parse_calls.append(raw)
        if len(parse_calls) == 1:
            raise ProbeContractError(
                "CFD-001 escaped quote must occur inside a quoted value.",
                probe_input=r'a=b\";c=d',
            )
        return original_parse(
            raw,
            observed_files,
            benchmark_task_id=benchmark_task_id,
        )

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
        patch(
            "nova.controller.loop.parse_hypothesis",
            side_effect=reject_first_probe_then_parse,
        ),
        patch(
            "nova.controller.loop.build_hypothesis_messages",
            wraps=loop_module.build_hypothesis_messages,
        ) as hypothesis_builder,
        patch(
            "nova.tools.behavioral_probe.run_behavioral_probe",
            wraps=behavioral_probe_module.run_behavioral_probe,
        ) as probe_runner,
        patch(
            "nova.controller.loop.build_prewrite_review_messages",
            wraps=loop_module.build_prewrite_review_messages,
        ) as review_builder,
    ):
        result = run_task(
            "Fix escaped quoted-value parsing.",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    assert result["agent_success"] is True, result
    assert result["causal_reviews"] == 1
    assert result["probes_attempted"] == 1 + len(loop_module._CFD001_ACCEPTANCE_CASES)
    assert result["probes_completed"] == 1 + len(loop_module._CFD001_ACCEPTANCE_CASES)
    assert result["changed_source_files"] == ["tokenizer.py"]
    assert result["postwrite_behavior_check_passed"] is True

    assert len(parse_calls) == 2
    assert hypothesis_builder.call_count == 2
    assert hypothesis_builder.call_args_list[0].kwargs[
        "probe_contract_feedback"
    ] is None
    assert hypothesis_builder.call_args_list[1].kwargs[
        "probe_contract_feedback"
    ] == {
        "reason": "CFD-001 escaped quote must occur inside a quoted value.",
        "rejected_input": r'a=b\";c=d',
    }
    assert [item["action"] for item in dispatches] == [
        "read_file",
        "write_file",
    ]
    assert probe_runner.call_count == 1 + len(loop_module._CFD001_ACCEPTANCE_CASES)
    assert probe_runner.call_args_list[0].args[1]["path"] == "tokenizer.py"
    for call in probe_runner.call_args_list[1:]:
        _, acceptance_probe = call.args
        assert acceptance_probe["path"] == "parser.py"
        assert acceptance_probe["function"] == "parse_record"
    review_builder.assert_called_once()

    write_events = [
        item for item in read_episode(settings)
        if item.get("action", {}).get("action") == "write_file"
    ]
    assert len(write_events) == 2
    assert write_events[0]["execution_status"] == "blocked_by_probe_contract"
    assert "CFD-001" in write_events[0]["probe_contract_error"]
    assert write_events[1]["execution_status"] == "succeeded"

def test_two_consecutive_probe_contract_rejections_stop_without_causal_review(
    tmp_path,
):
    settings = make_settings(tmp_path)
    settings.max_steps = 6

    # Two runtime backslashes before each quote: intentionally invalid.
    rejected_input = r'name="A \\"quoted; value\\"";status=ok'
    hypothesis = {
        "hypothesis": "The tokenizer mishandles escaped quotes.",
        "prediction": "The tokenizer raises an unterminated-quote error.",
        "probe": {
            "kind": "function_call",
            "path": "tokenizer.py",
            "function": "split_fields",
            "symbol": "",
            "expected_present": False,
            "args": [rejected_input],
            "kwargs": {},
            "expected_result": None,
            "expected_exception": {
                "type": "ValueError",
                "message": "Unterminated quoted value",
            },
        },
    }

    client = install_model(
        [
            plan(),
            action("read_file", path="parser.py"),
            action(
                "write_file",
                path="tokenizer.py",
                content=TOKENIZER_SOURCE,
            ),
            action(
                "write_file",
                path="tokenizer.py",
                content=TOKENIZER_SOURCE,
            ),
        ],
        hypothesis_response=hypothesis,
    )
    dispatches = []

    def dispatch(candidate, active_settings):
        dispatches.append(candidate)
        if candidate["action"] == "read_file":
            if candidate["path"] == "parser.py":
                return PARSER_SOURCE
            if candidate["path"] == "tokenizer.py":
                return TOKENIZER_SOURCE
        raise AssertionError(
            f"Unexpected dispatched action: {candidate['action']}"
        )

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
        patch(
            "nova.controller.loop.build_prewrite_review_messages"
        ) as review_builder,
    ):
        result = run_task(
            "Repair escaped quoted-value parsing. Do not modify or execute tests.",
            settings,
            benchmark_task_id="cross_file_dependency_001",
            planning_mode=True,
        )

    assert result["agent_success"] is False
    assert result["stop_reason"] == "probe_contract_blocked"
    assert result["probe_contract_blocked"] is True
    assert result["consecutive_probe_contract_rejections"] == 2
    assert result["causal_reviews"] == 0
    assert result["causal_review_blocked"] is False
    assert result["probes_attempted"] == 0
    assert result["probes_completed"] == 0
    assert result["changed_source_files"] == []
    assert [item["action"] for item in dispatches] == ["read_file"]
    review_builder.assert_not_called()

    hypothesis_calls = [
        call for call in client.chat_with_usage.call_args_list
        if call.kwargs.get("response_format", {})
        .get("json_schema", {}).get("name") == "nova_hypothesis"
    ]
    assert len(hypothesis_calls) == 2

    for call in hypothesis_calls:
        payload = json.loads(call.args[0][-1]["content"])
        assert payload["cfd001_probe_example"] == {
            "fields": [
                {"key": "name", "type": "quoted", "value": 'A "quoted; value"'},
                {"key": "status", "type": "unquoted", "value": "ok"},
            ]
        }

    journal = read_episode(settings)
    rejected_writes = [
        item for item in journal
        if item.get("action", {}).get("action") == "write_file"
    ]
    assert len(rejected_writes) == 2
    assert rejected_writes[0]["execution_status"] == "blocked_by_probe_contract"
    assert rejected_writes[1]["execution_status"] == (
        "blocked_by_probe_contract_limit"
    )
    assert all(
        item["hypothesis_test"]["failure_kind"] == "probe_contract"
        for item in rejected_writes
    )

