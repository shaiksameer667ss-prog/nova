from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from nova.config import Settings
from nova.controller import loop


TASK = """Read the workspace's settings file and return its exact contents.

The last known path is config/settings.json.

Do not create, write, delete, or modify any files.
Return the exact file contents in your final summary.
"""

EXPECTED = "NOVA-RELOCATION-CHECK-73"
MODEL = "qwen3.5:4b"


def run_trial(seed: int, planning: bool, root: Path) -> dict:
    arm = "planning" if planning else "control"
    trial_dir = root / f"seed-{seed}" / arm
    workspace = trial_dir / "workspace"
    database = trial_dir / "memory.sqlite3"

    workspace.mkdir(parents=True, exist_ok=False)

    source = workspace / "configs" / "settings.json"
    source.parent.mkdir(parents=True)
    source.write_text(EXPECTED, encoding="utf-8")

    settings = Settings(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model=MODEL,
        workspace=workspace,
        db=database,
        max_steps=8,
        temperature=0.2,
    )

    result = loop.run_task(
        TASK,
        settings,
        arm="RP1" if planning else "RP0",
        seed=seed,
        benchmark_task_id="planning_missing_path_recovery",
        planning_mode=planning,
    )

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row

    episode = conn.execute(
        "SELECT plan, actions FROM episodes ORDER BY created_at DESC LIMIT 1"
    ).fetchone()

    plan = json.loads(episode["plan"]) if episode["plan"] else None
    actions = json.loads(episode["actions"]) if episode["actions"] else []

    calls = [
        dict(row)
        for row in conn.execute("""
            SELECT purpose, status, total_tokens
            FROM model_calls ORDER BY rowid
        """).fetchall()
    ]

    conn.close()

    files = sorted(
        str(p.relative_to(workspace))
        for p in workspace.rglob("*")
        if p.is_file()
    )

    correct_read = any(
        item["action"].get("action") == "read_file"
        and item["action"].get("path") == "configs/settings.json"
        and item.get("observation") == EXPECTED
        for item in actions
    )

    listed_location = any(
        item["action"].get("action") == "list_files"
        and "configs/settings.json" in (item.get("observation") or "")
        for item in actions
    )

    done_summary = next(
        (
            item["action"].get("summary", "")
            for item in actions
            if item["action"].get("action") == "done"
        ),
        "",
    )

    verified = (
        correct_read
        and EXPECTED in done_summary
        and files == ["configs/settings.json"]
        and not any(
            item["action"].get("action") == "write_file"
            for item in actions
        )
    )

    return {
        "arm": arm,
        "agent_success": result["agent_success"],
        "verified_success": verified,
        "stop_reason": result["stop_reason"],
        "steps": result["steps"],
        "wall_seconds": result["wall_seconds"],
        "total_tokens": result["total_tokens"],
        "plan_revisions": result["plan_revisions"],
        "listed_actual_location": listed_location,
        "read_correct_file": correct_read,
        "actions": [
            {
                "action": item["action"],
                "status": item.get("execution_status"),
                "observation": item.get("observation"),
                "revision_error": item.get("plan_revision_error"),
            }
            for item in actions
        ],
        "plan": plan,
        "model_calls": calls,
    }


def main():
    seed = 4
    root = Path.home() / "nova-eval-lab" / "planning-relocation-pilot"
    root.mkdir(parents=True, exist_ok=True)

    print("Running baseline...")
    control = run_trial(seed, False, root)

    print("Running tool-aware planning...")
    treatment = run_trial(seed, True, root)

    report = {
        "experiment": "planning_missing_path_recovery",
        "model": MODEL,
        "seed": seed,
        "control": control,
        "treatment": treatment,
    }

    output = root / f"pair_seed{seed}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for label, trial in (("CONTROL", control), ("PLANNING", treatment)):
        print(f"\n=== {label} ===")
        for key in (
            "agent_success",
            "verified_success",
            "listed_actual_location",
            "read_correct_file",
            "plan_revisions",
            "steps",
            "total_tokens",
            "stop_reason",
        ):
            print(f"{key}: {trial[key]}")

        print("Actions:")
        for action in trial["actions"]:
            print(
                action["action"],
                "=>",
                action["status"],
                action.get("observation"),
            )

    print(f"\nFull report: {output}")


if __name__ == "__main__":
    main()
