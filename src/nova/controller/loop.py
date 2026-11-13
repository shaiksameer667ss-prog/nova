import ast
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nova.client import ModelClient
from nova.config import Settings
from nova.controller.causal_review import (
    CausalReviewError,
    build_causal_review_response_format,
    build_prewrite_review_messages,
    parse_prewrite_review,
)
from nova.controller.contracts import ACTION_CONTRACTS, validate_action
from nova.controller.hypothesis_testing import (
    HypothesisProbeError,
    ProbeContractError,
    build_hypothesis_messages,
    build_hypothesis_response_format,
    parse_hypothesis,
    required_dependency_probe_target,
)
from nova.controller.planning import (
    PLAN_RESPONSE_FORMAT,
    PlanValidationError,
    add_plan_revision,
    build_initial_plan_messages,
    build_replan_messages,
    create_plan_record,
    parse_plan,
    render_plan_context,
)
from nova.controller.reliability import FailureTracker
from nova.controller.runtime_lock import RuntimeLock
from nova.memory.db import (
    connect,
    create_action_execution,
    create_run,
    fail_run,
    finish_action_execution,
    finish_run,
    recover_interrupted_actions,
    recover_interrupted_runs,
    start_action_execution,
)
from nova.tools.file_ops import list_files, read_file, write_file


def _validate_python_source(path: str, content: str) -> str | None:
    """Return a deterministic syntax error for invalid Python source."""
    if not path.lower().endswith(".py"):
        return None
    try:
        ast.parse(content.removeprefix("\ufeff"), filename=path)
    except SyntaxError as exc:
        return (
            f"{path}: line {exc.lineno}, column {exc.offset}: "
            f"{exc.msg}"
        )
    return None

SYSTEM_PROMPT = """You are NOVA, an autonomous coding agent. You solve tasks by
proposing ONE action at a time, in JSON, and the system executes it.

Available actions:
- {"action": "write_file", "path": "<rel>", "content": "<text>"}
- {"action": "read_file", "path": "<rel>"}
- {"action": "list_files", "subdir": "."}
- {"action": "done", "summary": "<what you achieved>"}

Rules:
- Respond with JSON only. No prose, no markdown fences.
- Do one thing per turn.
- Do not run Python or execute shell commands.
- Do not attempt to read or modify hidden tests.
- The independent evaluation harness runs the tests.
- Call done only when you believe the fix is complete.
"""

# Flat JSON Schema: compatible with the tested Ollama 0.40.15 setup.
# Action-specific required fields are enforced by _validate_action below.
NOVA_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["write_file", "read_file", "list_files", "done"],
        },
        "path": {"type": "string"},
        "content": {"type": "string"},
        "subdir": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
}

NOVA_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "nova_action",
        "schema": NOVA_ACTION_SCHEMA,
    },
}

# Finding 7: controller guard for the tested tool and threshold.
LOOP_GUARD_TOOL = "list_files"
LOOP_GUARD_THRESHOLD = 3
MAX_PLAN_REVISIONS = 2
MAX_CAUSAL_REVIEWS = 3
MAX_PRE_GATE_ITERATIONS = 3
MAX_DONE_REJECTIONS = 2

_CFD001_ACCEPTANCE_CASES = (
    (
        "plain_fields",
        "name=Ada; role=writer",
        {"name": "Ada", "role": "writer"},
        None,
    ),
    (
        "semicolon_inside_quoted_value",
        'team="Research; Development";owner=Sam',
        {"team": "Research; Development", "owner": "Sam"},
        None,
    ),
    (
        "escaped_quote_and_embedded_semicolon",
        r'name="A \"quoted; value\"";status=ok',
        {"name": 'A "quoted; value"', "status": "ok"},
        None,
    ),
    (
        "whitespace_rules",
        '  name = " Ada Lovelace " ; role = engineer  ',
        {"name": " Ada Lovelace ", "role": "engineer"},
        None,
    ),
    (
        "trim_unquoted_values",
        "name = Alice  ; status = ok ",
        {"name": "Alice", "status": "ok"},
        None,
    ),
    ("empty_record", "", {}, None),
    ("whitespace_only_record", " \t ", {}, None),
    (
        "even_backslashes_before_closing_quote_2",
        r'path="C:\\";status=ok',
        {"path": "C:\\", "status": "ok"},
        None,
    ),
    (
        "even_backslashes_before_closing_quote_4",
        r'path="C:\\\\";status=ok',
        {"path": "C:\\\\", "status": "ok"},
        None,
    ),
    (
        "odd_backslashes_before_embedded_quote",
        r'note="a\\\"b;c";tag=x',
        {"note": 'a\\"b;c', "tag": "x"},
        None,
    ),
    (
        "multiple_fields_with_even_backslashes",
        r'p="x\\";q="y\\\\";r=z',
        {"p": "x\\", "q": "y\\\\", "r": "z"},
        None,
    ),
)


def _cfd001_postwrite_acceptance_probes():
    """Build deterministic public-API checks from the CFD-001 task contract."""
    return [
        {
            "kind": "function_call",
            "path": "parser.py",
            "function": "parse_record",
            "args": [source],
            "kwargs": {},
            "expected_result": expected,
            "expected_exception": expected_exception,
        }
        for _, source, expected, expected_exception in _CFD001_ACCEPTANCE_CASES
    ]


def _cfd001_evaluate_candidate(
    tokenizer_source: str,
    parser_source: str,
) -> dict:
    """Run CFD-001 acceptance cases against a candidate tokenizer.py.

    Executes parser.py and the candidate tokenizer.py in an isolated tempdir.
    Does not touch the real workspace, does not invoke Docker, does not
    depend on the causal reviewer or the behavioral probe sandbox.
    """
    import importlib.util
    import shutil
    import tempfile

    total = len(_CFD001_ACCEPTANCE_CASES)
    failures = []
    passed = 0

    tmpdir = tempfile.mkdtemp(prefix="cfd001_pregate_")
    original_tokenizer = sys.modules.get("tokenizer")
    try:
        Path(tmpdir, "tokenizer.py").write_text(tokenizer_source, encoding="utf-8")
        Path(tmpdir, "parser.py").write_text(parser_source, encoding="utf-8")

        tok_spec = importlib.util.spec_from_file_location(
            "cfd001_pregate_tokenizer",
            Path(tmpdir, "tokenizer.py"),
        )
        tok_mod = importlib.util.module_from_spec(tok_spec)
        sys.modules["tokenizer"] = tok_mod
        tok_spec.loader.exec_module(tok_mod)

        parser_spec = importlib.util.spec_from_file_location(
            "cfd001_pregate_parser",
            Path(tmpdir, "parser.py"),
        )
        parser_mod = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(parser_mod)

        for name, source, expected, expected_exception in _CFD001_ACCEPTANCE_CASES:
            try:
                actual = parser_mod.parse_record(source)
            except Exception as exc:  # noqa: BLE001 - case-level failure
                if (
                    expected_exception is not None
                    and isinstance(exc, expected_exception)
                ):
                    passed += 1
                    continue
                failures.append({
                    "case": name,
                    "input": source,
                    "expected": (
                        f"raise {expected_exception.__name__}"
                        if expected_exception is not None
                        else repr(expected)
                    ),
                    "actual": f"{type(exc).__name__}({str(exc)!r})",
                })
                continue

            if expected_exception is not None:
                failures.append({
                    "case": name,
                    "input": source,
                    "expected": f"raise {expected_exception.__name__}",
                    "actual": repr(actual),
                })
            elif actual == expected:
                passed += 1
            else:
                failures.append({
                    "case": name,
                    "input": source,
                    "expected": repr(expected),
                    "actual": repr(actual),
                })
    except Exception as exc:  # noqa: BLE001 - import failure = total failure
        return {
            "passed": 0,
            "failed": total,
            "total": total,
            "failures": [{
                "case": "import_error",
                "input": "",
                "expected": "valid module",
                "actual": f"{type(exc).__name__}({str(exc)!r})",
            }],
        }
    finally:
        if original_tokenizer is not None:
            sys.modules["tokenizer"] = original_tokenizer
        else:
            sys.modules.pop("tokenizer", None)
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "failures": failures,
    }


def _format_pre_gate_feedback(result: dict) -> str:
    """Format pre-gate failures as a user message. No prescription."""
    lines = [
        "Your proposed write to tokenizer.py was NOT executed.",
        f"{result['failed']} of {result['total']} CFD-001 acceptance cases failed:",
        "",
    ]
    for i, fail in enumerate(result["failures"], 1):
        lines.append(f"{i}. {fail['case']}")
        lines.append(f"   Input:    {fail['input']!r}")
        lines.append(f"   Expected: {fail['expected']}")
        lines.append(f"   Actual:   {fail['actual']}")
        lines.append("")
    lines.append("Correct the complete file and try again.")
    return "\\n".join(lines)


def _parse_action(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text)


def _validate_action(action: object) -> dict:
    """Validate an action using the shared declarative action contracts."""
    return validate_action(action)


def _dispatch(action: dict, settings: Settings) -> str:
    kind = action.get("action")
    if kind == "write_file":
        return write_file(settings.workspace, action["path"], action["content"])
    if kind == "read_file":
        return read_file(settings.workspace, action["path"])
    if kind == "list_files":
        return list_files(settings.workspace, action.get("subdir", "."))
    raise ValueError(f"unknown action: {kind}")


def _workspace_relative_key(workspace: Path, relative_path: str) -> str | None:
    """Normalize a workspace path and reject paths outside the workspace."""
    root = Path(workspace).resolve()
    try:
        target = (root / relative_path).resolve()
        return target.relative_to(root).as_posix()
    except (OSError, ValueError, TypeError):
        return None


def _snapshot_workspace_files(workspace: Path) -> set[str]:
    """Capture files that existed before NOVA began modifying the workspace."""
    root = Path(workspace).resolve()
    existing = set()

    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        key = _workspace_relative_key(
            root,
            candidate.relative_to(root).as_posix(),
        )
        if key is not None:
            existing.add(key)

    return existing


def _snapshot_workspace_hashes(workspace: Path) -> dict[str, str]:
    """Capture SHA-256 hashes of files beneath the workspace."""
    root = Path(workspace).resolve()
    hashes = {}
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        key = _workspace_relative_key(
            root,
            candidate.relative_to(root).as_posix(),
        )
        if key is not None:
            try:
                hashes[key] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                continue
    return hashes


def _run_task_locked(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
    use_json_schema: bool = True,
    planning_mode: bool = False,
    pre_selected_candidate: dict | None = None,
) -> dict:
    settings.workspace.mkdir(parents=True, exist_ok=True)

    client = ModelClient(settings)
    try:
        conn = connect(settings.db)
        try:
            # Recover previous runs and actions under the exclusive runtime lock.
            recovered_runs = recover_interrupted_runs(conn)
            run_id = str(uuid4())
            task_id = (
                benchmark_task_id
                if benchmark_task_id
                else f"adhoc_{run_id[:8]}"
            )
            recovered_actions = recover_interrupted_actions(conn, run_id)

            # Persist the run identity before the first model call.
            create_run(
                conn,
                run_id=run_id,
                task_id=task_id,
                arm=arm,
                seed=seed,
                model=settings.model,
            )

            try:
                return _run_task_with_resources(
                    task=task,
                    settings=settings,
                    arm=arm,
                    seed=seed,
                    benchmark_task_id=benchmark_task_id,
                    system_prompt=system_prompt,
                    use_json_schema=use_json_schema,
                    planning_mode=planning_mode,
                    pre_selected_candidate=pre_selected_candidate,
                    client=client,
                    conn=conn,
                    run_id=run_id,
                    task_id=task_id,
                    recovered_actions=recovered_actions,
                    recovered_runs=recovered_runs,
                )
            except Exception as exc:
                fail_run(conn, run_id, error_type=type(exc).__name__)
                raise
        finally:
            conn.close()
    finally:
        client.close()


def _run_task_with_resources(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
    use_json_schema: bool = True,
    planning_mode: bool = False,
    pre_selected_candidate: dict | None = None,
    *,
    client: ModelClient,
    conn,
    run_id: str,
    task_id: str,
    recovered_actions: dict[str, int],
    recovered_runs: int,
) -> dict:
    started = datetime.now(UTC)
    initial_workspace_hashes = _snapshot_workspace_hashes(settings.workspace)
    initial_workspace_files = set(initial_workspace_hashes)

    messages = [
        {"role": "system", "content": system_prompt if system_prompt is not None else SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task}"},
    ]

    transcript = []
    agent_success = False
    final_summary = ""
    pre_candidate_dispatched = False

    total_pt = 0
    total_ct = 0
    all_usage_complete = True

    plan_record = None
    planning_error_message = None
    planning_attempts = []
    replan_count = 0
    causal_review_count = 0
    causal_review_blocked = False
    probe_contract_blocked = False
    consecutive_probe_contract_rejections = 0
    dependency_target_blocked = False
    consecutive_dependency_target_rejections = 0
    causal_review_history = []
    observed_files = {}
    last_behavioral_probe = None
    last_probe_contract_feedback = None
    last_dependency_target_feedback = None
    probes_attempted = 0
    probes_completed = 0
    done_rejections = 0
    completion_gate = None
    completion_gate_blocked = False
    postwrite_behavior_check_passed = False
    consecutive_pre_gate_failures = 0
    pre_gate_blocked = False

    def observe_local_python_dependencies(importer_path, importer_source):
        """Read bounded, recursive local Python imports from the workspace."""
        import ast

        pending = [(importer_path, importer_source)]
        visited = {importer_path}
        discovered = {}

        while pending and len(discovered) < 16:
            current_path, current_source = pending.pop(0)
            try:
                tree = ast.parse(current_source, filename=current_path)
            except (SyntaxError, ValueError):
                continue

            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                ):
                    modules.add(node.module)

            parent = current_path.rpartition("/")[0]

            for module in sorted(modules):
                module_path = module.replace(".", "/")
                candidates = [
                    f"{module_path}.py",
                    f"{module_path}/__init__.py",
                ]
                if parent:
                    candidates = [
                        f"{parent}/{candidate}" for candidate in candidates
                    ] + candidates

                for candidate in candidates:
                    key = _workspace_relative_key(settings.workspace, candidate)
                    if (
                        key is None
                        or key not in initial_workspace_files
                        or key in visited
                    ):
                        continue

                    visited.add(key)
                    try:
                        dependency_source = read_file(settings.workspace, key)
                    except (OSError, UnicodeError, ValueError):
                        continue

                    observed_files[key] = dependency_source
                    discovered[key] = dependency_source
                    pending.append((key, dependency_source))
                    break

                if len(discovered) >= 16:
                    break

        return discovered

    def record_planning_model_call(purpose, usage_info, status):
        nonlocal total_pt, total_ct, all_usage_complete

        complete = usage_info.get("usage_complete") is True
        conn.execute(
            "INSERT INTO model_calls "
            "(id, run_id, purpose, model, prompt_tokens, completion_tokens, "
            "total_tokens, status, usage_complete, usage_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                run_id,
                purpose,
                settings.model,
                usage_info.get("prompt_tokens"),
                usage_info.get("completion_tokens"),
                usage_info.get("total_tokens"),
                status,
                int(complete),
                usage_info.get("usage_json"),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

        if complete:
            total_pt += usage_info["prompt_tokens"]
            total_ct += usage_info["completion_tokens"]
        else:
            all_usage_complete = False

    def request_plan(plan_messages, purpose):
        def record_attempt(attempt_number, call_purpose, raw, status):
            response_text = raw if isinstance(raw, str) else repr(raw)
            entry = {
                "purpose": call_purpose,
                "attempt": attempt_number,
                "status": status,
                "accepted": False,
                "response": response_text[:12000],
                "response_truncated": len(response_text) > 12000,
                "validation_error": None,
            }
            planning_attempts.append(entry)
            return entry

        raw_plan, usage_info, status = client.chat_with_usage(
            plan_messages,
            seed=seed,
            max_tokens=1024,
            response_format=PLAN_RESPONSE_FORMAT,
            reasoning_effort="none",
        )
        record_planning_model_call(purpose, usage_info, status)
        first_attempt = record_attempt(1, purpose, raw_plan, status)

        if status != "success":
            first_attempt["validation_error"] = f"model_call_failed: {status}"
            return None, f"model_call_failed: {status}"

        try:
            plan = parse_plan(raw_plan, task=task)
        except PlanValidationError as exc:
            validation_error = str(exc)
            first_attempt["validation_error"] = validation_error
        else:
            first_attempt["accepted"] = True
            return plan, None

        # Allow exactly one correction, but always apply the same strict
        # task-aware validator to the replacement plan.
        correction_messages = list(plan_messages)
        correction_messages.extend([
            {"role": "assistant", "content": (
                raw_plan if isinstance(raw_plan, str) else repr(raw_plan)
            )},
            {
                "role": "user",
                "content": (
                    "NOVA rejected your plan during task-aware validation. "
                    "Correct the specific violation and return a complete "
                    "replacement plan matching the required JSON schema. "
                    "Preserve the task objective and all valid parts of the "
                    "plan. Treat every task prohibition as an absolute "
                    "constraint. Do not describe, schedule, or imply a "
                    "prohibited operation, including in success criteria. "
                    "Do not weaken, reinterpret, or work around the "
                    "restriction. Validation error: "
                    f"{validation_error}"
                ),
            },
        ])

        correction_purpose = f"{purpose}_correction"
        corrected_raw, corrected_usage, corrected_status = (
            client.chat_with_usage(
                correction_messages,
                seed=seed,
                max_tokens=1024,
                response_format=PLAN_RESPONSE_FORMAT,
                reasoning_effort="none",
            )
        )
        record_planning_model_call(
            correction_purpose, corrected_usage, corrected_status
        )
        correction_attempt = record_attempt(
            2, correction_purpose, corrected_raw, corrected_status
        )

        if corrected_status != "success":
            error = f"model_call_failed_after_correction: {corrected_status}"
            correction_attempt["validation_error"] = error
            return None, error

        try:
            corrected_plan = parse_plan(corrected_raw, task=task)
        except PlanValidationError as exc:
            error = f"invalid_plan_response_after_correction: {exc}"
            correction_attempt["validation_error"] = str(exc)
            return None, error

        correction_attempt["accepted"] = True
        return corrected_plan, None

    def request_hypothesis_test(proposed_action):
        nonlocal last_probe_contract_feedback
        nonlocal last_dependency_target_feedback

        if not observed_files:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "No source files have been observed.",
                "causality_established": False,
            }, None

        dependency_probe_target = None
        if benchmark_task_id == "cross_file_dependency_001":
            dependency_probe_target = required_dependency_probe_target(
                observed_files,
                proposed_action.get("path"),
            )
        if (
            last_dependency_target_feedback is not None
            and last_dependency_target_feedback.get("required_probe")
            != dependency_probe_target
        ):
            last_dependency_target_feedback = None

        try:
            hypothesis_messages = build_hypothesis_messages(
                task,
                proposed_action,
                observed_files,
                probe_contract_feedback=last_probe_contract_feedback,
                benchmark_task_id=benchmark_task_id,
                dependency_probe_target=dependency_probe_target,
                dependency_target_feedback=last_dependency_target_feedback,
            )
            raw_hypothesis, usage_info, status = client.chat_with_usage(
                hypothesis_messages,
                seed=seed,
                max_tokens=768,
                response_format=build_hypothesis_response_format(
                    observed_files.keys(),
                    benchmark_task_id=benchmark_task_id,
                ),
                reasoning_effort="none",
            )
            record_planning_model_call(
                "hypothesis_generation",
                usage_info,
                status,
            )
            if status != "success":
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": f"Hypothesis model call failed: {status}",
                    "causality_established": False,
                }, raw_hypothesis

            hypothesis = parse_hypothesis(
                raw_hypothesis,
                observed_files,
                benchmark_task_id=benchmark_task_id,
            )
            last_probe_contract_feedback = None
            probe = hypothesis["probe"]
            if probe["kind"] != "function_call":
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": (
                        "A runtime function_call behavioral probe is required "
                        "before an existing-file repair."
                    ),
                    "causality_established": False,
                }, raw_hypothesis

            if dependency_probe_target is not None and (
                probe.get("path") != dependency_probe_target["path"]
                or probe.get("function") != dependency_probe_target["function"]
            ):
                reason = (
                    "The resolved dependency probe target is "
                    f"{dependency_probe_target['path']}::"
                    f"{dependency_probe_target['function']}; received "
                    f"{probe.get('path')}::{probe.get('function')}."
                )
                rejected_probe = {
                    "path": probe.get("path"),
                    "function": probe.get("function"),
                }
                last_dependency_target_feedback = {
                    "reason": reason,
                    "required_probe": dependency_probe_target,
                    "rejected_probe": rejected_probe,
                }
                return {
                    "verdict": "INCONCLUSIVE",
                    "reason": reason,
                    "failure_kind": "dependency_target",
                    "retryable": True,
                    "required_probe": dependency_probe_target,
                    "rejected_probe": rejected_probe,
                    "causality_established": False,
                }, raw_hypothesis

            last_dependency_target_feedback = None

            from nova.tools.behavioral_probe import run_behavioral_probe

            probe_result = run_behavioral_probe(
                observed_files,
                hypothesis["probe"],
            )
            return {
                "verdict": probe_result["verdict"],
                "hypothesis": hypothesis["hypothesis"],
                "prediction": hypothesis["prediction"],
                "probe": hypothesis["probe"],
                "probe_result": probe_result,
                "causality_established": False,
            }, raw_hypothesis

        except ProbeContractError as exc:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": str(exc),
                "rejected_probe_input": exc.probe_input,
                "failure_kind": "probe_contract",
                "retryable": True,
                "causality_established": False,
            }, locals().get("raw_hypothesis")
        except (HypothesisProbeError, TypeError, KeyError, ValueError) as exc:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": str(exc),
                "causality_established": False,
            }, locals().get("raw_hypothesis")

    def request_causal_review(proposed_action, hypothesis_test):
        review_context = {
            "execution_plan": plan_record["current"],
            "prior_causal_reviews": causal_review_history[-2:],
            "hypothesis_test": hypothesis_test,
        }
        review_messages = build_prewrite_review_messages(
            task,
            review_context,
            proposed_action,
            observed_files,
        )

        raw_review, usage_info, status = client.chat_with_usage(
            review_messages,
            seed=seed,
            max_tokens=1536,
            response_format=build_causal_review_response_format(
                observed_files.keys(),
                proposed_action["path"],
            ),
            reasoning_effort="none",
        )

        record_planning_model_call(
            "causal_review",
            usage_info,
            status,
        )

        if status != "success":
            return None, f"model_call_failed: {status}", raw_review

        try:
            return (
                parse_prewrite_review(
                    raw_review,
                    observed_files,
                    proposed_action["path"],
                ),
                None,
                raw_review,
            )
        except CausalReviewError as exc:
            return None, f"invalid_causal_review: {exc}", raw_review

    if planning_mode:
        initial_plan, planning_error_message = request_plan(
            build_initial_plan_messages(task),
            "planning",
        )
        if initial_plan is not None:
            plan_record = create_plan_record(initial_plan)
            messages.append({
                "role": "user",
                "content": render_plan_context(plan_record),
            })

    # Generalized repeated-failure detection for this run.
    failure_tracker = FailureTracker(threshold=LOOP_GUARD_THRESHOLD)
    loop_detected = False
    model_error = False

    for step in range(settings.max_steps if not planning_error_message else 0):
        if use_json_schema:
            raw, usage_info, status = client.chat_with_usage(
                messages,
                seed=seed,
                max_tokens=2048,
                response_format=NOVA_RESPONSE_FORMAT,
                reasoning_effort="none",
            )
        else:
            raw, usage_info, status = client.chat_with_usage(messages, seed=seed)

        conn.execute(
            "INSERT INTO model_calls (id, run_id, purpose, model, prompt_tokens, completion_tokens, total_tokens, status, usage_complete,usage_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), run_id, "agent_step", settings.model,
             usage_info["prompt_tokens"], usage_info["completion_tokens"], usage_info["total_tokens"],
             status, int(usage_info["usage_complete"]), usage_info["usage_json"],
             datetime.now(UTC).isoformat())
        )
        conn.commit()

        # CORRECTED LOGIC: Evaluate usage completeness before checking status
        if not usage_info["usage_complete"]:
            all_usage_complete = False
        else:
            total_pt += usage_info["prompt_tokens"]
            total_ct += usage_info["completion_tokens"]

        if status != "success":
            model_error = True
            transcript.append({"step": step, "error": status})
            break

        try:
            action = _parse_action(raw)
            if use_json_schema:
                action = _validate_action(action)
        except (json.JSONDecodeError, ValueError) as exc:
            error_kind = "bad json" if isinstance(exc, json.JSONDecodeError) else "invalid action"

            # Do not feed malformed assistant output back into the model context.
            messages.append({"role": "user", "content": "Your last message was not valid JSON. Reply with JSON only."})

            transcript.append({
                "step": step,
                "error": error_kind,
                "raw": raw[:20000],
                "raw_length": len(raw),
                "raw_truncated": len(raw) > 20000,
                "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "parse_error": str(exc),
                "finish_reason": usage_info.get("finish_reason"),
            })
            continue

        _pre_candidate_was_active = (
            pre_selected_candidate is not None and not pre_candidate_dispatched
        )
        if _pre_candidate_was_active and action.get("action") in ("done", "write_file"):
            action = {
                "action": "write_file",
                "path": pre_selected_candidate["path"],
                "content": pre_selected_candidate["content"],
            }
            transcript.append({
                "step": step,
                "assistant_output": raw,
                "action": action,
                "pre_candidate_substituted": True,
                "model_proposed_action_preview": raw[:500],
            })
        elif (
            pre_selected_candidate is not None
            and pre_candidate_dispatched
            and action.get("action") != "done"
        ):
            action = {
                "action": "done",
                "summary": "Pre-selected candidate dispatched; forcing completion.",
            }
            transcript.append({
                "step": step,
                "assistant_output": raw,
                "action": action,
                "forced_done_after_dispatch": True,
                "model_proposed_action_preview": raw[:500],
            })
        else:
            transcript.append({"step": step, "assistant_output": raw, "action": action})

        action_kind = action["action"]
        contract = ACTION_CONTRACTS[action_kind]

        # Existing files require an evidence-grounded review before modification.
        if planning_mode and action_kind == "write_file":
            syntax_error = _validate_python_source(
                action["path"], action["content"]
            )
            if syntax_error is not None:
                transcript[-1]["execution_status"] = (
                    "blocked_by_syntax_validation"
                )
                transcript[-1]["syntax_validation_error"] = syntax_error
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your proposed write was NOT executed. "
                        "Deterministic Python syntax validation failed: "
                        + syntax_error
                        + ". Correct the complete file and try again."
                    ),
                })
                continue
            target_key = _workspace_relative_key(
                settings.workspace,
                action["path"],
            )

            if (
                benchmark_task_id == "cross_file_dependency_001"
                and target_key == "tokenizer.py"
                and "parser.py" in observed_files
            ):
                pre_gate_result = _cfd001_evaluate_candidate(
                    action["content"],
                    observed_files["parser.py"],
                )
                transcript[-1]["pre_gate_result"] = pre_gate_result

                if pre_gate_result["failed"] > 0:
                    consecutive_pre_gate_failures += 1
                    transcript[-1]["execution_status"] = (
                        "blocked_by_pre_gate_acceptance"
                    )

                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": _format_pre_gate_feedback(pre_gate_result),
                    })

                    if consecutive_pre_gate_failures >= MAX_PRE_GATE_ITERATIONS:
                        pre_gate_blocked = True
                        transcript[-1]["execution_status"] = (
                            "blocked_by_pre_gate_limit"
                        )
                        break

                    continue

                consecutive_pre_gate_failures = 0

            if target_key in initial_workspace_files:
                if causal_review_count >= MAX_CAUSAL_REVIEWS:
                    causal_review_blocked = True
                    transcript[-1]["execution_status"] = (
                        "blocked_by_causal_review"
                    )
                    transcript[-1]["causal_review_error"] = (
                        "Maximum causal review count reached."
                    )
                    break

                hypothesis_test, raw_hypothesis = request_hypothesis_test(action)
                transcript[-1]["hypothesis_test"] = hypothesis_test

                if hypothesis_test.get("failure_kind") == "probe_contract":
                    consecutive_probe_contract_rejections += 1
                else:
                    consecutive_probe_contract_rejections = 0

                if hypothesis_test.get("failure_kind") == "dependency_target":
                    consecutive_dependency_target_rejections += 1
                else:
                    consecutive_dependency_target_rejections = 0

                transcript[-1]["consecutive_probe_contract_rejections"] = (
                    consecutive_probe_contract_rejections
                )
                transcript[-1]["consecutive_dependency_target_rejections"] = (
                    consecutive_dependency_target_rejections
                )
                probe_spec = hypothesis_test.get("probe")
                probe_observation = hypothesis_test.get("probe_result")
                if isinstance(probe_spec, dict):
                    probes_attempted += 1
                    if (
                        isinstance(probe_observation, dict)
                        and probe_observation.get("probe_completed") is True
                        and probe_observation.get("evidence_kind") == "sandbox_execution"
                    ):
                        probes_completed += 1
                        last_behavioral_probe = {
                            "probe": probe_spec,
                            "observed_paths": sorted(observed_files),
                        }
                if isinstance(raw_hypothesis, str):
                    transcript[-1]["hypothesis_response"] = raw_hypothesis[:4000]
                    transcript[-1]["hypothesis_response_length"] = len(raw_hypothesis)
                    transcript[-1]["hypothesis_response_sha256"] = (
                        hashlib.sha256(raw_hypothesis.encode("utf-8")).hexdigest()
                    )

                if (
                    hypothesis_test.get("retryable") is True
                    and hypothesis_test.get("failure_kind") == "dependency_target"
                ):
                    reason = hypothesis_test.get("reason") or (
                        "The behavioral probe did not target the resolved dependency."
                    )
                    transcript[-1]["execution_status"] = (
                        "blocked_by_dependency_target"
                    )
                    transcript[-1]["dependency_target_error"] = reason
                    transcript[-1]["required_dependency_probe"] = (
                        hypothesis_test.get("required_probe")
                    )
                    transcript[-1]["rejected_dependency_probe"] = (
                        hypothesis_test.get("rejected_probe")
                    )

                    messages.append({
                        "role": "assistant",
                        "content": raw,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your proposed write was NOT executed. The probe "
                            "was a valid function_call but selected the wrong "
                            "target. Use the exact required path/function pair: "
                            + json.dumps(
                                hypothesis_test.get("required_probe"),
                                ensure_ascii=False,
                            )
                            + ". Rejected target: "
                            + json.dumps(
                                hypothesis_test.get("rejected_probe"),
                                ensure_ascii=False,
                            )
                            + ". This requirement selects where to gather "
                            "behavioral evidence; it does NOT establish that "
                            "the dependency is defective. Generate a fresh "
                            "CFD-001 runtime probe for the required function."
                        ),
                    })

                    if consecutive_dependency_target_rejections >= 2:
                        dependency_target_blocked = True
                        transcript[-1]["execution_status"] = (
                            "blocked_by_dependency_target_limit"
                        )
                        transcript[-1]["dependency_target_stop_reason"] = (
                            "Two consecutive function-call probes selected a "
                            "different target from the uniquely resolved local "
                            "dependency function."
                        )
                        break

                    continue

                if (
                    hypothesis_test.get("retryable") is True
                    and hypothesis_test.get("failure_kind") == "probe_contract"
                ):
                    reason = hypothesis_test.get("reason") or (
                        "Probe input did not satisfy the CFD-001 record grammar."
                    )
                    transcript[-1]["execution_status"] = (
                        "blocked_by_probe_contract"
                    )
                    transcript[-1]["probe_contract_error"] = reason
                    last_probe_contract_feedback = {
                        "reason": reason,
                        "rejected_input": hypothesis_test.get(
                            "rejected_probe_input"
                        ),
                    }

                    messages.append({
                        "role": "assistant",
                        "content": raw,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your proposed write was NOT executed. The "
                            "behavioral probe was rejected by deterministic "
                            "CFD-001 input validation before sandbox execution. "
                            "This is a probe-generation failure, NOT a "
                            "prediction mismatch and NOT causal evidence.\n"
                            f"Validation reason: {reason}\n"
                            "Generate a fresh function_call probe. The user "
                            "payload contains cfd001_probe_example with a "
                            "validated runtime_value and its JSON encoding. "
                            "Copy runtime_value exactly into args[0]; do not "
                            "reconstruct or alter its backslashes. Keep it as "
                            "one complete, non-empty key=value record. "
                            "Reconsider the proposed repair using only valid "
                            "behavioral evidence."
                        ),
                    })

                    if consecutive_probe_contract_rejections >= 2:
                        probe_contract_blocked = True
                        transcript[-1]["execution_status"] = (
                            "blocked_by_probe_contract_limit"
                        )
                        transcript[-1]["probe_contract_stop_reason"] = (
                            "Two consecutive behavioral probes were rejected "
                            "by deterministic input validation."
                        )
                        break

                    continue

                probe_result = hypothesis_test.get("probe_result")
                probe_is_conclusive = (
                    hypothesis_test.get("verdict") in {
                        "PREDICTION_MATCHED",
                        "PREDICTION_MISMATCHED",
                    }
                    and isinstance(probe_result, dict)
                    and probe_result.get("probe_completed") is True
                    and probe_result.get("evidence_kind") == "sandbox_execution"
                    and probe_result.get("verdict")
                    == hypothesis_test.get("verdict")
                )
                if not probe_is_conclusive:
                    causal_review_blocked = True
                    transcript[-1]["execution_status"] = (
                        "blocked_by_hypothesis_test"
                    )
                    transcript[-1]["hypothesis_test_error"] = (
                        hypothesis_test.get("reason")
                        or (
                            probe_result.get("reason")
                            if isinstance(probe_result, dict)
                            else None
                        )
                        or "A completed Docker behavioral probe is required."
                    )
                    break

                causal_review_count += 1
                review, review_error, raw_review = request_causal_review(
                    action,
                    hypothesis_test,
                )

                if isinstance(raw_review, str):
                    transcript[-1]["causal_review_response"] = raw_review[:8000]
                    transcript[-1]["causal_review_response_length"] = len(raw_review)
                    transcript[-1]["causal_review_response_truncated"] = (
                        len(raw_review) > 8000
                    )
                    transcript[-1]["causal_review_response_sha256"] = (
                        hashlib.sha256(raw_review.encode("utf-8")).hexdigest()
                    )

                if review_error is not None:
                    causal_review_blocked = True
                    transcript[-1]["execution_status"] = (
                        "blocked_by_causal_review"
                    )
                    transcript[-1]["causal_review_error"] = review_error
                    break

                causal_review_history.append(review)
                transcript[-1]["causal_review"] = review

                if review["decision"] != "APPROVE":
                    transcript[-1]["execution_status"] = (
                        "blocked_by_causal_review"
                    )

                    messages.append({
                        "role": "assistant",
                        "content": raw,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your proposed write was NOT executed. "
                            "The causal review returned "
                            f"{review['decision']}.\n"
                            "Review findings:\n"
                            + json.dumps(
                                review,
                                ensure_ascii=False,
                                indent=2,
                            )
                            + "\nReconsider the diagnosis using these "
                            "findings. For REVISE, redirect the repair "
                            "toward the supported cause. For INVESTIGATE, "
                            "read the relevant dependency or source files "
                            "before proposing another write. Do not repeat "
                            "the rejected write without new evidence."
                        ),
                    })
                    continue

        # Hash the canonical action payload; do not copy its values into the journal.
        request_bytes = json.dumps(
            action,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        request_sha256 = hashlib.sha256(request_bytes).hexdigest()

        # Store field names only. File paths, file contents and summaries stay out
        # of the journal's human-readable request_summary.
        request_fields = ",".join(
            sorted(field for field in action if field != "action")
        )
        request_summary = f"{action_kind}(fields={request_fields})"

        execution_id = str(uuid4())
        idempotency_key = f"{run_id}:{step}"

        # Both journal commits happen before the tool is invoked.
        create_action_execution(
            conn,
            execution_id=execution_id,
            run_id=run_id,
            step=step,
            action_name=action_kind,
            effect=contract.effect,
            idempotency_key=idempotency_key,
            request_summary=request_summary,
            request_sha256=request_sha256,
        )
        start_action_execution(conn, execution_id)

        transcript[-1]["execution_id"] = execution_id

        if action_kind == "done":
            repair_task = any(
                term in task.lower()
                for term in ("fix", "repair", "bug", "correct", "resolve")
            )
            verification_required = (
                planning_mode
                and repair_task
                and any(
                    Path(name).suffix.lower() == ".py"
                    for name in initial_workspace_files
                )
            )

            if verification_required:
                verification = {
                    "verdict": "INCONCLUSIVE",
                    "reason": "No completed prewrite behavioral probe is available.",
                    "causality_established": False,
                }

                if last_behavioral_probe is not None:
                    try:
                        current_sources = {
                            name: read_file(settings.workspace, name)
                            for name in last_behavioral_probe["observed_paths"]
                        }
                        from nova.tools.behavioral_probe import run_behavioral_probe

                        if benchmark_task_id == "cross_file_dependency_001":
                            case_results = []
                            acceptance_probes = _cfd001_postwrite_acceptance_probes()
                            for (case_name, _, _, _), probe_spec in zip(
                                _CFD001_ACCEPTANCE_CASES,
                                acceptance_probes,
                                strict=True,
                            ):
                                probes_attempted += 1
                                try:
                                    case_result = run_behavioral_probe(
                                        current_sources,
                                        probe_spec,
                                    )
                                except Exception as exc:  # noqa: BLE001 - fail closed per case
                                    case_result = {
                                        "verdict": "INCONCLUSIVE",
                                        "reason": f"{type(exc).__name__}: {exc}",
                                        "causality_established": False,
                                    }

                                if case_result.get("probe_completed") is True:
                                    probes_completed += 1

                                case_results.append({
                                    "name": case_name,
                                    "verdict": case_result.get("verdict"),
                                    "probe_completed": (
                                        case_result.get("probe_completed") is True
                                    ),
                                    "evidence_kind": case_result.get("evidence_kind"),
                                    "actual_result": case_result.get("actual_result"),
                                    "actual_exception": case_result.get("actual_exception"),
                                    "reason": case_result.get("reason"),
                                })

                            all_cases_completed = bool(case_results) and all(
                                item["probe_completed"]
                                and item["evidence_kind"] == "sandbox_execution"
                                for item in case_results
                            )
                            all_cases_passed = all_cases_completed and all(
                                item["verdict"] == "PREDICTION_MATCHED"
                                for item in case_results
                            )
                            any_completed_mismatch = any(
                                item["probe_completed"]
                                and item["evidence_kind"] == "sandbox_execution"
                                and item["verdict"] == "PREDICTION_MISMATCHED"
                                for item in case_results
                            )

                            verification = {
                                "verdict": (
                                    "PREDICTION_MATCHED"
                                    if all_cases_passed
                                    else (
                                        "PREDICTION_MISMATCHED"
                                        if any_completed_mismatch
                                        else "INCONCLUSIVE"
                                    )
                                ),
                                "probe_kind": "task_contract_acceptance",
                                "case_count": len(case_results),
                                "cases_passed": sum(
                                    item["verdict"] == "PREDICTION_MATCHED"
                                    and item["probe_completed"]
                                    and item["evidence_kind"] == "sandbox_execution"
                                    for item in case_results
                                ),
                                "cases": case_results,
                                "prediction_matched": all_cases_passed,
                                "probe_completed": all_cases_completed,
                                "evidence_kind": (
                                    "sandbox_execution"
                                    if all_cases_completed
                                    else None
                                ),
                                "causality_established": False,
                            }
                        else:
                            probes_attempted += 1
                            verification = run_behavioral_probe(
                                current_sources,
                                last_behavioral_probe["probe"],
                            )
                            if verification.get("probe_completed") is True:
                                probes_completed += 1
                    except Exception as exc:  # noqa: BLE001 - verification must fail closed
                        verification = {
                            "verdict": "INCONCLUSIVE",
                            "reason": (
                                f"Post-write behavioral verification failed: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                            "causality_established": False,
                        }

                transcript[-1]["completion_verification"] = verification
                verification_passed = (
                    verification.get("verdict") == "PREDICTION_MATCHED"
                    and verification.get("probe_completed") is True
                    and verification.get("evidence_kind") == "sandbox_execution"
                )

                if not verification_passed:
                    done_rejections += 1
                    reason = (
                        "Completion rejected: post-write behavioral verification "
                        "did not pass. "
                        + json.dumps(verification, ensure_ascii=False, default=str)
                    )
                    transcript[-1]["execution_status"] = (
                        "rejected_by_completion_gate"
                    )
                    transcript[-1]["completion_gate_error"] = reason
                    reason_bytes = reason.encode("utf-8")
                    finish_action_execution(
                        conn,
                        execution_id,
                        status="failed",
                        result_sha256=hashlib.sha256(reason_bytes).hexdigest(),
                        result_length=len(reason_bytes),
                        error_type="CompletionGateRejected",
                        error_fingerprint=hashlib.sha256(reason_bytes).hexdigest(),
                    )

                    if done_rejections >= MAX_DONE_REJECTIONS:
                        completion_gate_blocked = True
                        break

                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": (
                            reason
                            + "\nDo not create probe scripts or claim verification. "
                            "Repair the actual source file. NOVA will rerun the "
                            +
                            (
                                "fixed CFD-001 task-contract acceptance cases "
                                "against the current workspace when you next "
                                "submit done. Continue until every case passes."
                                if benchmark_task_id == "cross_file_dependency_001"
                                else
                                "same behavioral probe against the current workspace "
                                "when you next submit done. Continue until its "
                                "post-write result matches the expected result."
                            )
                        ),
                    })
                    continue

                completion_gate = (
                    "postwrite_task_contract"
                    if benchmark_task_id == "cross_file_dependency_001"
                    else "postwrite_behavioral_probe"
                )
                postwrite_behavior_check_passed = True
            else:
                completion_gate = "not_required"

            final_summary = action["summary"]
            summary_bytes = final_summary.encode("utf-8")
            finish_action_execution(
                conn,
                execution_id,
                status="succeeded",
                result_sha256=hashlib.sha256(summary_bytes).hexdigest(),
                result_length=len(summary_bytes),
            )
            transcript[-1]["execution_status"] = "succeeded"
            if verification_required:
                transcript[-1]["completion_gate"] = completion_gate
            agent_success = True
            break

        action_failed = False
        try:
            observation = _dispatch(action, settings)

        except Exception as e:  # noqa: BLE001 - journal and contain arbitrary tool failures
            action_failed = True
            observation = f"ERROR: {type(e).__name__}: {e}"

            failure_decision = failure_tracker.record_failure(
                action_kind,
                type(e).__name__,
                str(e),
            )

            # A failed write may have partially changed the filesystem.
            # Retain uncertain status until recovery explicitly resolves it.
            execution_status = (
                "uncertain" if contract.effect == "write" else "failed"
            )

            finish_action_execution(
                conn,
                execution_id,
                status=execution_status,
                error_type=type(e).__name__,
                error_fingerprint=failure_decision.fingerprint,
            )

            transcript[-1]["execution_status"] = execution_status
            transcript[-1]["failure_fingerprint"] = (
                failure_decision.fingerprint
            )
            transcript[-1]["failure_occurrence_count"] = (
                failure_decision.occurrence_count
            )

            if failure_decision.should_stop:
                transcript[-1]["guard_triggered"] = True
                transcript[-1]["guard_reason"] = (
                    "repeated_failure_fingerprint"
                )
                loop_detected = True

        else:
            # A successful retry clears this tool's contribution to the
            # repeated-failure count.
            failure_tracker.record_success(action_kind)
            if (
                pre_selected_candidate is not None
                and not pre_candidate_dispatched
                and action_kind == "write_file"
            ):
                pre_candidate_dispatched = True
                transcript[-1]["pre_candidate_dispatched"] = True

            result_bytes = observation.encode("utf-8")
            finish_action_execution(
                conn,
                execution_id,
                status="succeeded",
                result_sha256=hashlib.sha256(result_bytes).hexdigest(),
                result_length=len(result_bytes),
            )
            transcript[-1]["execution_status"] = "succeeded"

            if action_kind == "read_file":
                observed_key = _workspace_relative_key(
                    settings.workspace,
                    action["path"],
                )
                if observed_key is not None:
                    observed_files[observed_key] = observation

                    if planning_mode:
                        dependencies = observe_local_python_dependencies(
                            observed_key,
                            observation,
                        )
                        if dependencies:
                            transcript[-1]["automatic_dependency_reads"] = sorted(
                                dependencies
                            )
                            dependency_context = "\n\n".join(
                                f"--- {dependency_path} ---\n{dependency_source}"
                                for dependency_path, dependency_source
                                in sorted(dependencies.items())
                            )
                            observation += (
                                "\n\nAutomatically inspected local Python "
                                "dependencies (read-only):\n"
                                + dependency_context
                            )

        transcript[-1]["observation"] = observation
        if loop_detected:
            break

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

        if (
            planning_mode
            and action_failed
            and plan_record is not None
            and replan_count < MAX_PLAN_REVISIONS
        ):
            replan_count += 1
            revised_plan, revision_error = request_plan(
                build_replan_messages(
                    task,
                    plan_record,
                    action,
                    observation,
                ),
                "replanning",
            )

            if revision_error is None:
                try:
                    plan_record = add_plan_revision(plan_record, revised_plan)
                except PlanValidationError as exc:
                    revision_error = f"invalid_plan_revision: {exc}"

            if revision_error is not None:
                transcript[-1]["plan_revision_error"] = revision_error
                messages.append({
                    "role": "user",
                    "content": (
                        "Plan revision failed. The previous plan remains active. "
                        "Use the actual observation, avoid unsupported claims, "
                        "and continue cautiously. Revision error: "
                        f"{revision_error[:500]}"
                    ),
                })
            else:
                transcript[-1]["plan_revision"] = replan_count
                messages.append({
                    "role": "user",
                    "content": render_plan_context(plan_record),
                })

    finished = datetime.now(UTC)
    wall = (finished - started).total_seconds()

    if loop_detected:
        stop_reason = "loop_detected"
    elif dependency_target_blocked:
        stop_reason = "dependency_target_blocked"
    elif probe_contract_blocked:
        stop_reason = "probe_contract_blocked"
    elif completion_gate_blocked:
        stop_reason = "done_rejected"
    elif pre_gate_blocked:
        stop_reason = "pre_gate_blocked"
    elif causal_review_blocked:
        stop_reason = "causal_review_blocked"
    elif model_error:
        stop_reason = "model_error"
    elif planning_error_message is not None:
        stop_reason = "planning_error"
    elif agent_success:
        stop_reason = "completed"
    else:
        stop_reason = "max_steps_reached"

    pt_val = total_pt if all_usage_complete else None
    ct_val = total_ct if all_usage_complete else None
    tt_val = (total_pt + total_ct) if all_usage_complete else None

    conn.execute(
        "INSERT INTO episodes (id, run_id, task_id, created_at, plan, actions, outcome, success) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            run_id,
            task_id,
            finished.isoformat(),
            json.dumps(plan_record, ensure_ascii=False)
            if plan_record is not None else None,
            json.dumps(transcript),
            final_summary,
            int(agent_success),
        ),
    )
    finish_run(
        conn,
        run_id,
        success=agent_success,
        wall_seconds=wall,
        prompt_tokens=pt_val,
        completion_tokens=ct_val,
        total_tokens=tt_val,
        usage_complete=all_usage_complete,
        termination_reason=stop_reason,
        finished_at=finished.isoformat(),
    )

    final_workspace_hashes = _snapshot_workspace_hashes(settings.workspace)
    changed_source_files = sorted(
        name
        for name, original_hash in initial_workspace_hashes.items()
        if final_workspace_hashes.get(name) != original_hash
    )
    new_files = sorted(set(final_workspace_hashes) - set(initial_workspace_hashes))

    return {
        "run_id": run_id,
        "task_id": task_id,
        "agent_success": agent_success,
        "summary": final_summary,
        "steps": len(transcript),
        "wall_seconds": wall,
        "prompt_tokens": pt_val,
        "completion_tokens": ct_val,
        "total_tokens": tt_val,
        "usage_complete": all_usage_complete,
        "used_json_schema": use_json_schema,
        "stop_reason": stop_reason,
        "recovered_actions": recovered_actions,
        "recovered_runs": recovered_runs,
        "planning_mode": planning_mode,
        "planning_error": planning_error_message,
        "planning_attempts": planning_attempts,
        "causal_reviews": causal_review_count,
        "causal_review_blocked": causal_review_blocked,
        "probe_contract_blocked": probe_contract_blocked,
        "consecutive_probe_contract_rejections": (
            consecutive_probe_contract_rejections
        ),
        "dependency_target_blocked": dependency_target_blocked,
        "consecutive_dependency_target_rejections": (
            consecutive_dependency_target_rejections
        ),
        "changed_source_files": changed_source_files,
        "new_files": new_files,
        "done_rejections": done_rejections,
        "completion_gate": completion_gate,
        "completion_gate_blocked": completion_gate_blocked,
        "probes_attempted": probes_attempted,
        "probes_completed": probes_completed,
        "postwrite_behavior_check_passed": postwrite_behavior_check_passed,
        "pre_gate_blocked": pre_gate_blocked,
        "plan_revisions": len(plan_record["revisions"])
        if plan_record is not None else 0,
    }


def run_task(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
    use_json_schema: bool = True,
    planning_mode: bool = False,
    pre_selected_candidate: dict | None = None,
) -> dict:
    """Run NOVA under an exclusive database lock and recover old journal entries."""
    lock_path = settings.db.resolve().with_name(
        settings.db.name + ".runtime.lock"
    )

    with RuntimeLock(lock_path):
        return _run_task_locked(
            task=task,
            settings=settings,
            arm=arm,
            seed=seed,
            benchmark_task_id=benchmark_task_id,
            system_prompt=system_prompt,
            use_json_schema=use_json_schema,
            planning_mode=planning_mode,
            pre_selected_candidate=pre_selected_candidate,
        )
