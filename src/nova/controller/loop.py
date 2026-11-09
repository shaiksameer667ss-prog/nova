import json
import hashlib
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

def _parse_action(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text)


def _validate_action(action: object) -> dict:
    if not isinstance(action, dict):
        raise ValueError("Action must be a JSON object.")

    kind = action.get("action")

    rules = {
        "write_file": ({"path", "content"}, set()),
        "read_file": ({"path"}, set()),
        "list_files": (set(), {"subdir"}),
        "done": ({"summary"}, set()),
    }

    if not isinstance(kind, str) or kind not in rules:
        raise ValueError(f"Unknown or missing action: {kind!r}")

    required, optional = rules[kind]
    allowed = {"action"} | required | optional

    missing = required - set(action)
    unexpected = set(action) - allowed

    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"Unexpected fields: {sorted(unexpected)}")

    for field in required | (optional & set(action)):
        if not isinstance(action[field], str):
            raise ValueError(f"Field {field!r} must be a string.")

    return action


def _dispatch(action: dict, settings: Settings) -> str:
    kind = action.get("action")
    if kind == "write_file":
        return write_file(settings.workspace, action["path"], action["content"])
    if kind == "read_file":
        return read_file(settings.workspace, action["path"])
    if kind == "list_files":
        return list_files(settings.workspace, action.get("subdir", "."))
    raise ValueError(f"unknown action: {kind}")

def run_task(
    task: str,
    settings: Settings,
    arm: str = "A",
    seed: int = 0,
    benchmark_task_id: str | None = None,
    system_prompt: str | None = None,
) -> dict:
    settings.workspace.mkdir(parents=True, exist_ok=True)
    client = ModelClient(settings)
    conn = connect(settings.db)

    run_id = str(uuid4())
    task_id = benchmark_task_id if benchmark_task_id else f"adhoc_{run_id[:8]}"
    started = datetime.now(timezone.utc)

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

    # Matched experimental conditions:
    # V0_NOECHO_THINK_OFF: no schema, reasoning disabled.
    # V0_JSON_SCHEMA: same settings, with JSON Schema enforcement.
    reasoning_disabled = arm in {"V0_NOECHO_THINK_OFF", "V0_JSON_SCHEMA"}
    structured_output = arm == "V0_JSON_SCHEMA"

    schema_sha256 = (
        hashlib.sha256(
            json.dumps(NOVA_ACTION_SCHEMA, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if structured_output else None
    )

    for step in range(settings.max_steps):
        call_options = {"seed": seed}

        if reasoning_disabled:
            call_options["reasoning_effort"] = "none"
            call_options["max_tokens"] = 2048

        if structured_output:
            call_options["response_format"] = NOVA_RESPONSE_FORMAT

        raw, usage_info, status = client.chat_with_usage(
            messages, **call_options
        )
        
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
            if reasoning_disabled:
                action = _validate_action(action)

        except (json.JSONDecodeError, ValueError) as exc:
            error_kind = (
                "bad json"
                if isinstance(exc, json.JSONDecodeError)
                else "invalid action"
            )

            # Preserve no-echo behavior and original retry wording.
            messages.append({
                "role": "user",
                "content": "Your last message was not valid JSON. Reply with JSON only.",
            })

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
        "usage_complete": all_usage_complete,
        "generation_mode": (
            "json_schema" if structured_output
            else "unconstrained_think_off" if reasoning_disabled
            else "legacy"
        ),
        "reasoning_effort": "none" if reasoning_disabled else "server_default",
        "max_tokens": 2048 if reasoning_disabled else None,
        "action_schema_sha256": schema_sha256,
    }