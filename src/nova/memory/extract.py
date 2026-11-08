import json
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from nova.config import get_settings
from nova.memory.db import connect
from nova.client import ModelClient

EXTRACT_PROMPT = """You are an expert AI researcher. Below is a successful execution trace of an agent solving a coding task.

Your goal is to extract a reusable, generalizable diagnostic procedure (a "skill") from this experience.

CRITICAL INSTRUCTIONS:
- Do NOT write a procedure that just repeats the exact code fix (e.g., "add self._pending.clear()").
- Instead, write a *diagnostic method* that can be applied to similar bugs in the future.
- The procedure should guide a future agent on how to *find* and *verify* the fix, not just hand them the answer.

Task ID: {task_id}
Execution Trace:
{trace}

Respond with JSON only, exactly in this format:
{{
  "trigger_conditions": "A brief description of when this skill should be applied",
  "procedure": "A text description or numbered list of diagnostic steps"
}}
"""

def main(run_id: str):
    settings = get_settings()
    conn = connect(settings.db)
    
    # 1. Fetch the run
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        print(f"Error: Run ID {run_id} not found.")
        return
        
    if not run["verified_success"]:
        print(f"Error: Run ID {run_id} was not independently verified. Refusing to learn from unverified experience.")
        return

    # 2. Fetch the EXACT episode using run_id
    episode = conn.execute("SELECT * FROM episodes WHERE run_id = ?", (run_id,)).fetchone()
    if not episode:
        print(f"Error: Episode not found for run {run_id}.")
        return

    trace = json.loads(episode["actions"])
    trace_str = json.dumps(trace, indent=2)
    
    # 3. Ask the model to extract the skill
    print(f"Extracting skill from verified run {run_id}...")
    client = ModelClient(settings)
    prompt = EXTRACT_PROMPT.format(task_id=run["task_id"], trace=trace_str)
    
    raw_response = client.chat([{"role": "user", "content": prompt}], temperature=0.1)
    
    raw_response = raw_response.strip()
    if raw_response.startswith("```json"):
        raw_response = raw_response[7:-3]
    elif raw_response.startswith("```"):
        raw_response = raw_response[3:-3]

    try:
        skill_data = json.loads(raw_response)
    except json.JSONDecodeError:
        print("Error: Model did not return valid JSON. Raw output:")
        print(raw_response)
        return

    procedure_val = skill_data.get("procedure", "")
    if isinstance(procedure_val, list):
        procedure_str = "\n".join(str(item) for item in procedure_val)
    else:
        procedure_str = str(procedure_val)

    trigger_val = skill_data.get("trigger_conditions", "")
    if isinstance(trigger_val, list):
        trigger_str = ", ".join(str(item) for item in trigger_val)
    else:
        trigger_str = str(trigger_val)

    # 4. Save the skill with strict lineage
    skill_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    conn.execute(
        """INSERT INTO skills 
           (id, version, created_at, source_task_ids, source_run_id, source_episode_id, trigger_conditions, procedure, status) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            skill_id, 
            1, 
            now, 
            json.dumps([run["task_id"]]), 
            run_id,
            episode["id"],
            trigger_str, 
            procedure_str, 
            "candidate"
        )
    )
    conn.commit()
    conn.close()
    client.close()

    print("\n✅ Skill extracted and saved successfully!")
    print(f"Skill ID: {skill_id}")
    print(f"Trigger:  {trigger_str}")
    print(f"Procedure:\n{procedure_str}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m nova.memory.extract <run_id>")
        sys.exit(2)
    main(sys.argv[1])