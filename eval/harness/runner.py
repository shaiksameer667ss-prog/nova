import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from nova.config import get_settings
from nova.controller.loop import run_task


def _load_task(task_dir: Path) -> dict:
    with open(task_dir / "task.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_prompt(task: dict, arm: str) -> str:
    prompt = task["prompt"]
    gold_label = task.get("gold_skill_arm_label", "GOLD")
    if arm == gold_label and task.get("gold_skill"):
        prompt = (
            f"{prompt}\n\n"
            f"A previously learned procedure you may consider:\n"
            f"{task['gold_skill']}"
        )
    return prompt


def _run_hidden_tests(workspace: Path, hidden_dir: Path) -> tuple[bool, str]:
    """Copy workspace + hidden tests into a fresh temp dir, run pytest there.
    Agent never sees hidden tests. This is the independent verifier."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        for src in workspace.rglob("*"):
            if src.is_file():
                rel = src.relative_to(workspace)
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dest)

        for src in hidden_dir.rglob("*.py"):
            shutil.copy(src, tmp_path / src.name)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()


def run_one(task_dir: Path, arm: str, seed: int) -> dict:
    settings = get_settings()
    task = _load_task(task_dir)

    workspace = settings.workspace
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for src in (task_dir / "repo").iterdir():
        if src.is_file():
            shutil.copy(src, workspace / src.name)

    prompt = _build_prompt(task, arm)

    gold_label = task.get("gold_skill_arm_label", "GOLD")
    skill_injected = arm == gold_label and bool(task.get("gold_skill"))

    agent_result = run_task(prompt, settings, arm=arm, seed=seed)

    verified_success, test_output = _run_hidden_tests(
        workspace, task_dir / "hidden_tests"
    )

    return {
        "task_id": task["id"],
        "arm": arm,
        "seed": seed,
        "skill_injected": skill_injected,
        "agent_success": agent_result["agent_success"],
        "verified_success": verified_success,
        "steps": agent_result["steps"],
        "wall_seconds": round(agent_result["wall_seconds"], 1),
        "test_output_tail": test_output[-400:] if test_output else "",
        "run_id": agent_result["run_id"],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m eval.harness.runner <task_dir> [arm] [seed]")
        sys.exit(2)
    task_dir = Path(sys.argv[1])
    arm = sys.argv[2] if len(sys.argv) > 2 else "A"
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    result = run_one(task_dir, arm, seed)
    print(json.dumps(result, indent=2))