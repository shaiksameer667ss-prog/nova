import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from nova.client import ModelClient
from nova.config import Settings
from nova.controller.contracts import ACTION_CONTRACTS, validate_action
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

MAX_COMPLETION_VERIFICATION_ATTEMPTS = 2


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


def _run_task_locked(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
    use_json_schema: bool = True,
    completion_verifier: Callable[[], bool] | None = None,
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
                    completion_verifier=completion_verifier,
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
    completion_verifier: Callable[[], bool] | None = None,
    *,
    client: ModelClient,
    conn,
    run_id: str,
    task_id: str,
    recovered_actions: dict[str, int],
    recovered_runs: int,
) -> dict:
    started = datetime.now(UTC)

    messages = [
        {"role": "system", "content": system_prompt if system_prompt is not None else SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task}"},
    ]

    transcript = []
    agent_success = False
    final_summary = ""

    total_pt = 0
    total_ct = 0
    all_usage_complete = True

    # Generalized repeated-failure detection for this run.
    failure_tracker = FailureTracker(threshold=LOOP_GUARD_THRESHOLD)
    loop_detected = False
    model_error = False
    completion_verification_failed = False
    completion_verifier_error = False
    completion_verification_attempts = 0

    for step in range(settings.max_steps):
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

        transcript.append({"step": step, "assistant_output": raw, "action": action})

        action_kind = action["action"]
        contract = ACTION_CONTRACTS[action_kind]

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
            try:
                verification_passed = (
                    completion_verifier is None
                    or completion_verifier() is True
                )
            except Exception:  # noqa: BLE001 - fail closed on verifier errors
                finish_action_execution(
                    conn,
                    execution_id,
                    status="failed",
                    error_type="CompletionVerifierError",
                )
                transcript[-1]["execution_status"] = "failed"
                transcript[-1]["error_type"] = "CompletionVerifierError"
                transcript[-1]["observation"] = "Completion verifier error."
                completion_verifier_error = True
                break

            if verification_passed:
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
                agent_success = True
                break

            completion_verification_attempts += 1
            finish_action_execution(
                conn,
                execution_id,
                status="failed",
                error_type="CompletionVerificationFailed",
            )
            transcript[-1]["execution_status"] = "failed"
            transcript[-1]["error_type"] = "CompletionVerificationFailed"
            transcript[-1]["verification_attempt"] = (
                completion_verification_attempts
            )

            transcript[-1]["observation"] = "Completion verification failed."

            if (
                completion_verification_attempts
                >= MAX_COMPLETION_VERIFICATION_ATTEMPTS
            ):
                completion_verification_failed = True
                break

            # Preserve conversation context but never expose verifier output.
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "Completion verification failed. The task is not yet "
                    "verified. Re-examine the task requirements and workspace, "
                    "make any necessary corrections, then try again. Do not "
                    "claim completion until independent verification passes."
                ),
            })
            continue

        try:
            observation = _dispatch(action, settings)

        except Exception as e:  # noqa: BLE001 - journal and contain arbitrary tool failures
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

            result_bytes = observation.encode("utf-8")
            finish_action_execution(
                conn,
                execution_id,
                status="succeeded",
                result_sha256=hashlib.sha256(result_bytes).hexdigest(),
                result_length=len(result_bytes),
            )
            transcript[-1]["execution_status"] = "succeeded"

        transcript[-1]["observation"] = observation
        if loop_detected:
            break

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

    finished = datetime.now(UTC)
    wall = (finished - started).total_seconds()

    if loop_detected:
        stop_reason = "loop_detected"
    elif model_error:
        stop_reason = "model_error"
    elif completion_verifier_error:
        stop_reason = "completion_verifier_error"
    elif completion_verification_failed:
        stop_reason = "completion_verification_failed"
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
        (str(uuid4()), run_id, task_id, finished.isoformat(), None,
         json.dumps(transcript), final_summary, int(agent_success)),
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
    }


def run_task(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
    use_json_schema: bool = True,
    completion_verifier: Callable[[], bool] | None = None,
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
            completion_verifier=completion_verifier,
        )
