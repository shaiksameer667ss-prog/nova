import json
import shutil
import subprocess
import sys
import tempfile
import hashlib
from pathlib import Path

import yaml

from nova.config import get_settings
from nova.controller.loop import run_task
from nova.memory.db import connect

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

# Strict IDs
ACQUISITION_RUN_ID = "38d8accd-392a-4483-9180-71abae3d76b0"
EXTRACTED_SKILL_ID = "41e7d45f-2e84-4be3-99ed-34f21338c58b"

def _load_task(task_dir: Path) -> dict:
    with open(task_dir / "task.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _build_prompt(task: dict, arm: str, conn) -> tuple[str, dict]:
    prompt = task["prompt"]
    memory_info = {"injected": 0, "type": None, "item_id": None, "source_run_id": None, "sha256": None}
    
    gold_label = task.get("gold_skill_arm_label", "GOLD")
    
    if arm == gold_label and task.get("gold_skill"):
        text = task['gold_skill']
        prompt = f"{prompt}\n\nA previously learned procedure you may consider:\n{text}"
        memory_info.update({"injected": 1, "type": "gold", "sha256": hashlib.sha256(text.encode()).hexdigest()})
        
    elif arm == "B": # Patch Memory
        prompt = f"{prompt}\n\n{PATCH_MEMORY}"
        memory_info.update({"injected": 1, "type": "patch", "sha256": hashlib.sha256(PATCH_MEMORY.encode()).hexdigest()})
        
    elif arm == "C": # Raw Experience (Strict Lookup + Fail-Fast)
        episode = conn.execute("SELECT id, actions FROM episodes WHERE run_id = ?", (ACQUISITION_RUN_ID,)).fetchone()
        if not episode:
            raise ValueError(f"CRITICAL: Could not find raw experience for run {ACQUISITION_RUN_ID}")
            
        text = f"Here is a raw JSON execution trace of a previous similar task:\n{episode['actions']}"
        prompt = f"{prompt}\n\n{text}"
        memory_info.update({
            "injected": 1, "type": "raw_experience", "item_id": episode["id"], 
            "source_run_id": ACQUISITION_RUN_ID, "sha256": hashlib.sha256(text.encode()).hexdigest()
        })
            
    elif arm == "D": # Learned Skill (Strict Lookup + Fail-Fast)
        skill = conn.execute("SELECT id, source_run_id, trigger_conditions, procedure FROM skills WHERE id = ?", (EXTRACTED_SKILL_ID,)).fetchone()
        if not skill:
            raise ValueError(f"CRITICAL: Could not find learned skill {EXTRACTED_SKILL_ID}")
            
        text = f"When: {skill['trigger_conditions']}\nProcedure:\n{skill['procedure']}"
        prompt = f"{prompt}\n\nA previously learned procedure you may consider:\n{text}"
        memory_info.update({
            "injected": 1, "type": "learned_skill", "item_id": skill["id"], 
            "source_run_id": skill["source_run_id"], "sha256": hashlib.sha256(text.encode()).hexdigest()
        })

    return prompt, memory_info

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
            cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
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

    prompt, mem_info = _build_prompt(task, arm, conn)
    
    agent_result = run_task(prompt, settings, arm=arm, seed=seed, benchmark_task_id=task["id"])
    verified_success, test_output = _run_hidden_tests(workspace, task_dir / "hidden_tests")

    conn.execute(
        "UPDATE runs SET verified_success = ?, memory_injected = ?, memory_type = ?, "
        "memory_item_id = ?, memory_source_run_id = ?, memory_sha256 = ? WHERE id = ?",
        (
            int(verified_success), mem_info["injected"], mem_info["type"], 
            mem_info["item_id"], mem_info["source_run_id"], mem_info["sha256"], 
            agent_result["run_id"]
        ),
    )
    conn.commit()
    conn.close()

    return {
        "task_id": task["id"],
        "arm": arm,
        "seed": seed,
        "memory_injected": bool(mem_info["injected"]),
        "memory_item_id": mem_info["item_id"],
        "verified_success": verified_success,
        "steps": agent_result["steps"],
        "wall_seconds": round(agent_result["wall_seconds"], 1),
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