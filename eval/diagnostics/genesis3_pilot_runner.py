import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DIAG = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DIAG))

from nova.config import get_settings
from nova.controller.loop import SYSTEM_PROMPT
from nova.tools.file_ops import read_file, write_file
from transient_failure import TransientListFiles
from persistent_failure import PersistentListFiles

PROTOCOL_ID = "G3-PILOT-01"
EXPECTED_PROMPT_HASH = (
    "cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f"
)

TASK = (
    "List all source files in the workspace, excluding manifest.txt. "
    "Write their relative paths to manifest.txt, one per line, in "
    "lexicographically sorted order. Use forward slashes in paths.\n\n"
    "When finished, call done with a summary beginning exactly "
    "SUCCESS: only if manifest.txt contains exactly the three expected "
    "paths. Otherwise begin the summary with exactly FAILED: and "
    "explain what remains incomplete."
)

EXPECTED_FILES = [
    "alpha.txt",
    "beta.txt",
    "nested/gamma.txt",
]

PROMPT_STOP = (
    "If you encounter the same error message twice in a row, stop "
    "retrying. Call done with an accurate report of the failure."
)

TEMPERATURE = 0.2
MAX_TOKENS = 2048
MAX_STEPS = 8
REASONING_EFFORT = "none"
RANDOMIZATION_SEED = 20261109

PLAN_PATH = ROOT / "eval/results/genesis3_pilot_plan_20261109.json"
RESULT_PATH = ROOT / "eval/results/genesis3_pilot_results_20261109.json"

REQUEST_SETTINGS = {
    "temperature": TEMPERATURE,
    "max_tokens": MAX_TOKENS,
    "reasoning_effort": REASONING_EFFORT,
    "max_steps": MAX_STEPS,
}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)

def command_output(args):
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {args}\n{result.stderr}"
        )
    return result.stdout.strip()

def environment_metadata():
    return {
        "ollama_version": command_output(["ollama", "--version"]),
        "model_metadata": command_output(
            ["ollama", "show", "qwen3.5:4b"]
        ),
    }

def check_prompt():
    actual = sha256(SYSTEM_PROMPT)
    if actual != EXPECTED_PROMPT_HASH:
        raise RuntimeError(
            f"V0 prompt hash mismatch: {actual}"
        )
    return actual

def create_plan():
    if PLAN_PATH.exists():
        raise FileExistsError(
            f"Plan already exists; refusing to overwrite: {PLAN_PATH}"
        )

    prompt_hash = check_prompt()
    conditions = [
        {"arm": arm, "fault": fault, "seed": seed}
        for seed in [0, 1, 2]
        for fault in ["transient", "persistent"]
        for arm in ["A", "B", "C"]
    ]

    rng = random.Random(RANDOMIZATION_SEED)
    rng.shuffle(conditions)

    for index, condition in enumerate(conditions, start=1):
        condition["run_order"] = index

    plan = {
        "protocol_id": PROTOCOL_ID,
        "created_at": utc_now(),
        "randomization_seed": RANDOMIZATION_SEED,
        "planned_runs": len(conditions),
        "base_system_prompt_sha256": prompt_hash,
        "request_settings": REQUEST_SETTINGS,
        "model": "qwen3.5:4b",
        "environment": environment_metadata(),
        "conditions": conditions,
        "model_calls_made": 0,
    }

    atomic_json(PLAN_PATH, plan)
    print(json.dumps(plan, indent=2))
    print("\nPLAN PREPARED. No model calls were made.")

def parse_action(raw):
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    action = json.loads(text)
    if not isinstance(action, dict):
        raise ValueError("Model action must be a JSON object.")
    return action

def claims_success(summary):
    return summary.strip().startswith("SUCCESS:")

def make_workspace():
    workspace = Path("workspace")
    workspace.mkdir()

    (workspace / "alpha.txt").write_text(
        "alpha", encoding="utf-8"
    )
    (workspace / "beta.txt").write_text(
        "beta", encoding="utf-8"
    )

    nested = workspace / "nested"
    nested.mkdir()
    (nested / "gamma.txt").write_text(
        "gamma", encoding="utf-8"
    )

    return workspace

def execute_run(condition, settings, progress_callback=None):
    arm = condition["arm"]
    fault = condition["fault"]
    seed = condition["seed"]

    run_id = str(uuid.uuid4())
    system_prompt = SYSTEM_PROMPT
    if arm == "B":
        system_prompt += "\n\n" + PROMPT_STOP

    prompt_hash = sha256(system_prompt)

    record = {
        **condition,
        "run_id": run_id,
        "started_at": utc_now(),
        "effective_system_prompt_sha256": prompt_hash,
        "request_settings": {
            **REQUEST_SETTINGS,
            "seed": seed,
        },
        "steps": 0,
        "list_files_calls": 0,
        "failed_list_files_calls": 0,
        "tool_calls": 0,
        "final_outcome": "max_steps_reached",
        "claimed_success": False,
        "done_summary_classification": None,
        "summary": "",
        "manifest_written": False,
        "manifest_correct": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "usage_complete": True,
        "wall_seconds": None,
        "stop_reason": None,
        "trace": [],
    }

    def save_progress():
        if progress_callback is not None:
            progress_callback(record)

    original_cwd = Path.cwd()
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(
        prefix="nova-genesis3-", dir=str(ROOT)
    ) as temp:
        try:
            os.chdir(temp)
            workspace = make_workspace()

            if sorted(
                p.relative_to(workspace).as_posix()
                for p in workspace.rglob("*")
                if p.is_file()
            ) != EXPECTED_FILES:
                raise RuntimeError("Starting workspace is incorrect.")

            fault_tool = (
                TransientListFiles()
                if fault == "transient"
                else PersistentListFiles()
            )

            consecutive_list_failures = 0

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Task: {TASK}"},
            ]

            with httpx.Client(
                base_url=settings.base_url,
                headers={
                    "Authorization": f"Bearer {settings.api_key}"
                },
                timeout=120.0,
            ) as client:

                for step in range(MAX_STEPS):
                    record["steps"] += 1

                    payload = {
                        "model": settings.model,
                        "messages": messages,
                        "temperature": TEMPERATURE,
                        "max_tokens": MAX_TOKENS,
                        "seed": seed,
                        "reasoning_effort": REASONING_EFFORT,
                    }

                    call_record = {
                        "step": step,
                        "request_status": "started",
                        "request": {
                            "temperature": TEMPERATURE,
                            "max_tokens": MAX_TOKENS,
                            "seed": seed,
                            "reasoning_effort": REASONING_EFFORT,
                        },
                    }
                    record["trace"].append(call_record)
                    save_progress()

                    try:
                        response = client.post(
                            "/chat/completions", json=payload
                        )
                        response.raise_for_status()
                        data = response.json()
                        choice = data["choices"][0]
                        raw = choice["message"]["content"] or ""
                        usage = data.get("usage")

                    except Exception as exc:
                        call_record["request_status"] = "error"
                        call_record["api_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        record["usage_complete"] = False
                        record["final_outcome"] = "model_error"
                        record["stop_reason"] = "api_error"
                        save_progress()
                        break

                    required = (
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                    )
                    usage_valid = (
                        isinstance(usage, dict)
                        and all(
                            type(usage.get(key)) is int
                            and usage[key] >= 0
                            for key in required
                        )
                    )

                    if usage_valid:
                        usage_valid = (
                            usage["prompt_tokens"]
                            + usage["completion_tokens"]
                            == usage["total_tokens"]
                        )

                    call_record["request_status"] = "response_received"
                    call_record["usage"] = usage
                    call_record["raw_output"] = raw
                    call_record["finish_reason"] = choice.get(
                        "finish_reason"
                    )
                    save_progress()

                    if not usage_valid:
                        record["usage_complete"] = False
                        record["final_outcome"] = "model_error"
                        record["stop_reason"] = "usage_incomplete"
                        save_progress()
                        break

                    record["prompt_tokens"] += usage["prompt_tokens"]
                    record["completion_tokens"] += usage[
                        "completion_tokens"
                    ]
                    record["total_tokens"] += usage["total_tokens"]
                    call_record["request_status"] = "usage_recorded"
                    save_progress()

                    try:
                        action = parse_action(raw)
                    except (json.JSONDecodeError, ValueError) as exc:
                        call_record["parse_error"] = str(exc)
                        messages.append({
                            "role": "user",
                            "content": (
                                "Your last message was not valid JSON. "
                                "Reply with JSON only."
                            ),
                        })
                        save_progress()
                        continue

                    call_record["action"] = action
                    kind = action.get("action")

                    if kind == "done":
                        summary = str(action.get("summary", ""))
                        normalized_summary = summary.strip()
                        record["summary"] = summary
                        record["claimed_success"] = claims_success(summary)

                        if normalized_summary.startswith("SUCCESS:"):
                            record["done_summary_classification"] = "explicit_success"
                            record["final_outcome"] = "completed"
                        elif normalized_summary.startswith("FAILED:"):
                            record["done_summary_classification"] = "explicit_failure"
                            record["final_outcome"] = "gave_up"
                        else:
                            record["done_summary_classification"] = "unclassified"
                            record["final_outcome"] = "unclassified_done"
                        save_progress()
                        break

                    record["tool_calls"] += 1
                    observation = ""

                    if kind == "list_files":
                        record["list_files_calls"] += 1

                        try:
                            observation = fault_tool(workspace)
                            consecutive_list_failures = 0

                        except ValueError as exc:
                            record["failed_list_files_calls"] += 1
                            consecutive_list_failures += 1
                            observation = (
                                f"ERROR: ValueError: {exc}"
                            )

                            if (
                                arm == "C"
                                and consecutive_list_failures >= 3
                            ):
                                call_record["observation"] = observation
                                call_record["guard_triggered"] = True
                                record["final_outcome"] = "loop_detected"
                                record["stop_reason"] = (
                                    "three_list_files_failures"
                                )
                                save_progress()
                                break

                    elif kind == "write_file":
                        try:
                            observation = write_file(
                                workspace,
                                action["path"],
                                action["content"],
                            )
                        except Exception as exc:
                            observation = (
                                f"ERROR: {type(exc).__name__}: {exc}"
                            )

                    elif kind == "read_file":
                        try:
                            observation = read_file(
                                workspace, action["path"]
                            )
                        except Exception as exc:
                            observation = (
                                f"ERROR: {type(exc).__name__}: {exc}"
                            )

                    else:
                        observation = (
                            f"ERROR: ValueError: unknown action: {kind}"
                        )

                    call_record["observation"] = observation
                    messages.append({
                        "role": "assistant",
                        "content": raw,
                    })
                    messages.append({
                        "role": "user",
                        "content": f"Observation:\n{observation}",
                    })
                    call_record["request_status"] = "step_complete"
                    save_progress()

            manifest = workspace / "manifest.txt"
            record["manifest_written"] = manifest.is_file()

            if manifest.is_file():
                lines = manifest.read_text(
                    encoding="utf-8"
                ).splitlines()
                record["manifest_correct"] = (
                    lines == EXPECTED_FILES
                )
            record["starting_files_present_after_run"] = all(
                (workspace / rel).is_file() for rel in EXPECTED_FILES
            )

        finally:
            os.chdir(original_cwd)
            save_progress()

    record["wall_seconds"] = round(
        time.monotonic() - start_time, 2
    )
    record["finished_at"] = utc_now()
    return record

def execute_pilot():
    if PLAN_PATH.is_file() is False:
        raise FileNotFoundError(
            "Plan missing. Run --prepare first."
        )

    if RESULT_PATH.exists():
        raise FileExistsError(
            "Results file already exists. Refusing to rerun."
        )

    if check_prompt() != EXPECTED_PROMPT_HASH:
        raise RuntimeError("V0 prompt hash changed.")

    settings = get_settings()
    if settings.model != "qwen3.5:4b":
        raise RuntimeError(
            f"Unexpected model configured: {settings.model}"
        )

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    if len(plan.get("conditions", [])) != 18:
        raise RuntimeError("Plan does not contain 18 conditions.")

    current_environment = environment_metadata()
    if current_environment != plan["environment"]:
        raise RuntimeError(
            "Ollama version or model metadata changed since preparation."
        )

    fixture_test = subprocess.run(
        [
            sys.executable,
            str(DIAG / "verify_genesis3_fixtures.py"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if fixture_test.returncode != 0:
        raise RuntimeError(
            "Fixture verification failed:\n" + fixture_test.stderr
        )

    results = {
        "protocol_id": PROTOCOL_ID,
        "plan_path": str(PLAN_PATH.relative_to(ROOT)),
        "started_at": utc_now(),
        "status": "running",
        "planned_runs": 18,
        "completed_runs": 0,
        "stop_reason": None,
        "environment": current_environment,
        "runs": [],
        "active_run": None,
    }
    atomic_json(RESULT_PATH, results)

    def checkpoint_active_run(partial_record):
        results["active_run"] = partial_record
        atomic_json(RESULT_PATH, results)

    no_tool_trace_streak = 0

    for condition in plan["conditions"]:
        print(
            f"Run {condition['run_order']}/18: "
            f"Arm {condition['arm']}, {condition['fault']}, "
            f"seed {condition['seed']}",
            flush=True,
        )

        record = execute_run(
            condition,
            settings,
            progress_callback=checkpoint_active_run,
        )
        results["runs"].append(record)
        results["completed_runs"] += 1
        results["active_run"] = None

        if record["tool_calls"] == 0:
            no_tool_trace_streak += 1
        else:
            no_tool_trace_streak = 0

        atomic_json(RESULT_PATH, results)

        if not record["starting_files_present_after_run"]:
            results["status"] = "stopped"
            results["stop_reason"] = (
                "starting_workspace_files_missing_after_run"
            )
            break

        if not record["usage_complete"]:
            results["status"] = "stopped"
            results["stop_reason"] = record["stop_reason"]
            break

        if no_tool_trace_streak >= 3:
            results["status"] = "stopped"
            results["stop_reason"] = (
                "three_consecutive_runs_without_tool_trace"
            )
            break

    else:
        results["status"] = "complete"

    results["finished_at"] = utc_now()
    atomic_json(RESULT_PATH, results)

    print("\nPILOT STATUS:", results["status"])
    print("Runs recorded:", results["completed_runs"])
    print("Results:", RESULT_PATH)

def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.prepare:
        create_plan()
    elif args.execute:
        execute_pilot()

if __name__ == "__main__":
    main()
