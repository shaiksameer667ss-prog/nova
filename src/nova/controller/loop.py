import json
from datetime import datetime, timezone
from uuid import uuid4

from nova.client import ModelClient
from nova.config import Settings
from nova.memory.db import connect
from nova.tools.file_ops import list_files, read_file, write_file

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

def _parse_action(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text)

def _dispatch(action: dict, settings: Settings) -> str:
    kind = action.get("action")
    if kind == "write_file":
        return write_file(settings.workspace, action["path"], action["content"])
    if kind == "read_file":
        return read_file(settings.workspace, action["path"])
    if kind == "list_files":
        return list_files(settings.workspace, action.get("subdir", "."))
    raise ValueError(f"unknown action: {kind}")

def run_task(task: str, settings: Settings, arm: str = "A", seed: int = 0, benchmark_task_id: str | None = None) -> dict:
    settings.workspace.mkdir(parents=True, exist_ok=True)
    client = ModelClient(settings)
    conn = connect(settings.db)

    run_id = str(uuid4())
    task_id = benchmark_task_id if benchmark_task_id else f"adhoc_{run_id[:8]}"
    started = datetime.now(timezone.utc)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task}"},
    ]

    transcript = []
    agent_success = False
    final_summary = ""
    
    total_pt = 0
    total_ct = 0
    all_usage_complete = True

    for step in range(settings.max_steps):
        raw, usage_info, status = client.chat_with_usage(messages, seed=seed)
        
        conn.execute(
            "INSERT INTO model_calls (id, run_id, purpose, model, prompt_tokens, completion_tokens, total_tokens, status, usage_complete, usage_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), run_id, "agent_step", settings.model, 
             usage_info["prompt_tokens"], usage_info["completion_tokens"], usage_info["total_tokens"],
             status, int(usage_info["usage_complete"]), usage_info["usage_json"],
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        # CORRECTED LOGIC: Evaluate usage completeness before checking status
        if not usage_info["usage_complete"]:
            all_usage_complete = False
        else:
            total_pt += usage_info["prompt_tokens"]
            total_ct += usage_info["completion_tokens"]

        if status != "success":
            transcript.append({"step": step, "error": status})
            break
        
        try:
            action = _parse_action(raw)
        except json.JSONDecodeError:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Your last message was not valid JSON. Reply with JSON only."})
            transcript.append({"step": step, "error": "bad json", "raw": raw[:200]})
            continue

        transcript.append({"step": step, "assistant_output": raw, "action": action})

        if action.get("action") == "done":
            agent_success = True
            final_summary = action.get("summary", "")
            break

        try:
            observation = _dispatch(action, settings)
        except Exception as e:
            observation = f"ERROR: {type(e).__name__}: {e}"

        transcript[-1]["observation"] = observation
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

    finished = datetime.now(timezone.utc)
    wall = (finished - started).total_seconds()
    
    pt_val = total_pt if all_usage_complete else None
    ct_val = total_ct if all_usage_complete else None
    tt_val = (total_pt + total_ct) if all_usage_complete else None

    conn.execute(
        "INSERT INTO runs (id, task_id, arm, seed, model, success, cost_usd, "
        "wall_seconds, git_sha, created_at, prompt_tokens, completion_tokens, total_tokens, usage_complete) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, task_id, arm, seed, settings.model, int(agent_success),
         0.0, wall, None, finished.isoformat(), pt_val, ct_val, tt_val, int(all_usage_complete)),
    )
    conn.execute(
        "INSERT INTO episodes (id, run_id, task_id, created_at, plan, actions, outcome, success) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid4()), run_id, task_id, finished.isoformat(), None,
         json.dumps(transcript), final_summary, int(agent_success)),
    )
    conn.commit()
    conn.close()
    client.close()

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
        "usage_complete": all_usage_complete
    }