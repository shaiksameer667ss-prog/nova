"""Paired baseline-versus-planning pilot with a controlled tool failure."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from nova.config import Settings
from nova.controller import loop

TASK = """Create a file named answer.txt.

The entire file must contain exactly this text, with no trailing newline:
NOVA-ADAPTIVE-PLANNING-OK

Read the file back to verify its content before reporting completion.
Do not create any other files.
"""

EXPECTED = "NOVA-ADAPTIVE-PLANNING-OK"
MODELS = ("qwen3.5:4b", "qwen3.5:9b")


def run_trial(model: str, seed: int, planning: bool, root: Path) -> dict:
    arm = "planning" if planning else "control"
    trial_dir = root / model.replace(":", "-") / f"seed-{seed}" / arm
    workspace = trial_dir / "workspace"
    database = trial_dir / "memory.sqlite3"

    workspace.mkdir(parents=True, exist_ok=False)

    settings = Settings(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model=model,
        workspace=workspace,
        db=database,
        max_steps=8,
        temperature=0.2,
    )

    original_dispatch = loop._dispatch
    failure = {"injected": False, "action": None}

    def dispatch_with_one_failure(action: dict, current_settings: Settings) -> str:
        if not failure["injected"] and action.get("action") != "done":
            failure["injected"] = True
            failure["action"] = action.get("action")
            raise OSError("PILOT_INJECTED_TRANSIENT_TOOL_FAILURE")
        return original_dispatch(action, current_settings)

    with patch.object(
        loop,
        "_dispatch",
        side_effect=dispatch_with_one_failure,
    ):
        result = loop.run_task(
            TASK,
            settings,
            arm="AP1" if planning else "AP0",
            seed=seed,
            benchmark_task_id="adaptive_planning_tool_recovery_pilot",
            planning_mode=planning,
        )

    answer = workspace / "answer.txt"
    actual_content = answer.read_text(encoding="utf-8") if answer.is_file() else None
    actual_files = sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*")
        if path.is_file()
    )

    # Independent oracle: exact required file set and exact file contents.
    verified = actual_files == ["answer.txt"] and actual_content == EXPECTED

    conn = sqlite3.connect(database)
    calls = conn.execute(
        "SELECT purpose, status, usage_complete, prompt_tokens, "
        "completion_tokens, total_tokens FROM model_calls ORDER BY rowid"
    ).fetchall()
    conn.close()

    usage_complete = bool(calls) and all(row[2] == 1 for row in calls)
    total_tokens = sum(row[5] for row in calls) if usage_complete else None

    return {
        "model": model,
        "seed": seed,
        "arm": arm,
        "planning_mode": planning,
        "agent_success": result["agent_success"],
        "independently_verified_success": verified,
        "false_success": bool(result["agent_success"] and not verified),
        "stop_reason": result["stop_reason"],
        "steps": result["steps"],
        "plan_revisions": result["plan_revisions"],
        "injected_failure": failure["injected"],
        "failed_action": failure["action"],
        "wall_seconds": result["wall_seconds"],
        "total_tokens": total_tokens,
        "usage_complete": usage_complete,
        "model_calls": [
            {
                "purpose": row[0],
                "status": row[1],
                "usage_complete": bool(row[2]),
                "total_tokens": row[5],
            }
            for row in calls
        ],
        "files": actual_files,
        "actual_content": actual_content,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS, default="qwen3.5:4b")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    root = Path.home() / "nova-eval-lab" / "adaptive-planning-pilot"
    root.mkdir(parents=True, exist_ok=True)

    print(f"Model: {args.model}")
    print(f"Seed: {args.seed}")
    print("Running control arm...")

    control = run_trial(args.model, args.seed, False, root)

    print("Running adaptive-planning arm...")
    treatment = run_trial(args.model, args.seed, True, root)

    report = {
        "experiment": "adaptive_planning_tool_recovery_pilot",
        "version": "0.1",
        "task": "exact_file_creation_with_one_injected_tool_failure",
        "model": args.model,
        "seed": args.seed,
        "control": control,
        "treatment": treatment,
    }

    output = root / f"pair_{args.model.replace(':', '-')}_seed{args.seed}.json"
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n=== PAIRED RESULTS ===")
    for label, row in (("CONTROL", control), ("PLANNING", treatment)):
        print(f"\n{label}")
        print("Verified success:", row["independently_verified_success"])
        print("Agent claimed success:", row["agent_success"])
        print("Injected failure:", row["injected_failure"])
        print("Failed action:", row["failed_action"])
        print("Plan revisions:", row["plan_revisions"])
        print("Steps:", row["steps"])
        print("Total tokens:", row["total_tokens"])
        print("Wall seconds:", round(row["wall_seconds"], 2))
        print("Stop reason:", row["stop_reason"])

    print(f"\nReport: {output}")
    print("\nPILOT COMPLETE")


if __name__ == "__main__":
    main()
