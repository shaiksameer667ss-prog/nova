import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from nova.config import get_settings
from nova.controller.loop import run_task
from nova.memory.db import connect

# The exact patch from the source task (Counter)
PATCH_MEMORY = """
Here is a previous successful code change for a similar problem:
--- a/counter.py
+++ b/counter.py
@@ -15,5 +15,6 @@ class Counter:
     def flush(self):
         if self._pending:
             self._committed += sum(self._pending)
+            self._pending.clear()
         return self._committed
"""

def _load_task(task_dir: Path) -> dict:
    with open(task_dir / "task.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _build_prompt(task: dict, arm: str, conn) -> str:
    prompt = task["prompt"]
    gold_label = task.get("gold_skill_arm_label", "GOLD")
    
    if arm == gold_label and task.get("gold_skill"):
        prompt = f"{prompt}\n\nA previously learned procedure you may consider:\n{task['gold_skill']}"
        
    elif arm == "B": # Patch Memory
        prompt = f"{prompt}\n\n{PATCH_MEMORY}"
        
    elif arm == "C": # Raw Experience
        # Fetch the trace from the DB (source task: parcel_pipe)
        episode = conn.execute("SELECT actions FROM episodes WHERE task_id = 'parcel_pipe' LIMIT 1").fetchone()
        if episode:
            prompt = f"{prompt}\n\nHere is a raw JSON execution trace of a previous similar task:\n{episode['actions']}"
            
    elif arm == "D": # Learned Skill
        # Fetch the skill from the DB
        skill = conn.execute("SELECT trigger_conditions, procedure FROM skills WHERE status = 'candidate' ORDER BY created_at DESC LIMIT 1").fetchone()
        if skill:
            skill_text = f"When: {skill['trigger_conditions']}\nProcedure:\n{skill['procedure']}"
            prompt = f"{prompt}\n\nA previously learned procedure you may consider:\n{skill_text}"

    return prompt

def _run_hidden_tests(workspace: Path, hidden_dir: Path) -> tuple[bool, str]:
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
    conn = connect(settings.db)

    workspace = settings.workspace
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for src in (task_dir / "repo").iterdir():
        if src.is_file():
            shutil.copy(src, workspace / src.name)

    prompt = _build_prompt(task, arm, conn)
    
    gold_label = task.get("gold_skill_arm_label", "GOLD")
    memory_injected = (arm in ("B", "C", "D") or (arm == gold_label and bool(task.get("gold_skill"))))

    # Pass the benchmark task ID to the controller
    agent_result = run_task(prompt, settings, arm=arm, seed=seed, benchmark_task_id=task["id"])

    verified_success, test_output = _run_hidden_tests(
        workspace, task_dir / "hidden_tests"
    )

    conn.execute(
        "UPDATE runs SET verified_success = ? WHERE id = ?",
        (int(verified_success), agent_result["run_id"]),
    )
    conn.commit()
    conn.close()

    return {
        "task_id": task["id"],
        "arm": arm,
        "seed": seed,
        "memory_injected": memory_injected,
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