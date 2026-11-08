import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from nova.config import get_settings
from nova.client import ModelClient
from nova.memory.db import connect


ROOT = Path.cwd()

V0_PATH = ROOT / "data/prompts/v0.txt"
BASELINE_PATH = ROOT / "eval/results/nova_genesis_v0_state_management_5seeds_20261108.json"

DIAGNOSTIC_RUN_ID = "312c856d-0331-4e66-b49c-65183735636b"

OUTPUT_PATH = ROOT / "data/prompts/v1_candidate_attempt3.txt"
RAW_PATH = ROOT / "data/prompts/v1_generation_attempt3_response.txt"
META_PATH = ROOT / "eval/results/nova_genesis_v1_generation_attempt3_20261108.json"

ALLOWED_TASKS = {"inventory_batch", "scan_state"}

BEGIN_MARKER = "<<<NOVA_GENESIS_ADDITION_BEGIN>>>"
END_MARKER = "<<<NOVA_GENESIS_ADDITION_END>>>"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_trace(actions):
    result = []

    for item in actions:
        entry = {
            "step": item.get("step"),
            "error": item.get("error"),
        }

        raw = item.get("assistant_output", "")

        if item.get("error") == "bad json":
            entry["malformed_response_preview"] = item.get("raw", "")[:200]
            entry["parse_error"] = item.get("parse_error")

        elif raw:
            try:
                action = json.loads(raw)
                entry["action"] = action.get("action")
                entry["action_details"] = action

                if isinstance(entry["action_details"].get("content"), str):
                    entry["action_details"]["content"] = (
                        entry["action_details"]["content"][:900]
                    )
            except (ValueError, TypeError):
                entry["raw_preview"] = raw[:300]

        observation = item.get("observation")
        if observation:
            entry["observation"] = str(observation)[:350]

        result.append(entry)

    return result


def main():
    for path in (OUTPUT_PATH, RAW_PATH, META_PATH):
        if path.exists():
            raise RuntimeError(
                f"Refusing to overwrite existing generation artifact: {path}"
            )

    if not V0_PATH.is_file() or not BASELINE_PATH.is_file():
        raise FileNotFoundError("V0 prompt or approved training dataset missing.")

    v0 = V0_PATH.read_text(encoding="utf-8")
    parent_hash = digest(v0)

    baseline = json.loads(
        BASELINE_PATH.read_text(encoding="utf-8-sig")
    )

    records = baseline.get("runs", [])

    if len(records) != 10:
        raise RuntimeError("Expected exactly ten approved training runs.")

    training_traces = []
    conn = connect(get_settings().db)

    try:
        for record in records:
            task_id = record["task_id"]

            if task_id not in ALLOWED_TASKS:
                raise RuntimeError(f"Unauthorized training task: {task_id}")

            if not record.get("verified_success"):
                raise RuntimeError("Unverified training example rejected.")

            if record.get("memory_injected"):
                raise RuntimeError("Memory-contaminated training example rejected.")

            run_id = record["run_id"]

            db_run = conn.execute(
                "SELECT verified_success, usage_complete FROM runs WHERE id = ?",
                (run_id,)
            ).fetchone()

            if not db_run or db_run["verified_success"] != 1:
                raise RuntimeError(f"Invalid training run: {run_id}")

            episode = conn.execute(
                "SELECT actions FROM episodes WHERE run_id = ?",
                (run_id,)
            ).fetchone()

            if not episode or not episode["actions"]:
                raise RuntimeError(f"Missing training transcript: {run_id}")

            actions = json.loads(episode["actions"])

            training_traces.append({
                "task_id": task_id,
                "seed": record["seed"],
                "run_id": run_id,
                "verified_success": True,
                "steps": record["steps"],
                "total_tokens": record["total_tokens"],
                "trace": compact_trace(actions)
            })

        # Include the separately inspected, full diagnostic reproduction.
        diagnostic = conn.execute("""
            SELECT r.task_id, r.arm, r.verified_success,
                   r.usage_complete, e.actions
            FROM runs r
            JOIN episodes e ON e.run_id = r.id
            WHERE r.id = ?
        """, (DIAGNOSTIC_RUN_ID,)).fetchone()

        if (
            not diagnostic
            or diagnostic["task_id"] != "inventory_batch"
            or diagnostic["arm"] != "A"
            or diagnostic["verified_success"] != 1
            or diagnostic["usage_complete"] != 1
        ):
            raise RuntimeError("Diagnostic training run failed provenance checks.")

        diagnostic_trace = json.loads(diagnostic["actions"])

        malformed = [
            item for item in diagnostic_trace
            if item.get("error") == "bad json"
        ]

        if not malformed:
            raise RuntimeError("Expected malformed-response evidence missing.")

        complete_example = malformed[0].get("raw", "")

        if len(complete_example) < 300:
            raise RuntimeError("Full malformed example is unavailable.")

        diagnostic_evidence = {
            "run_id": DIAGNOSTIC_RUN_ID,
            "task_id": "inventory_batch",
            "malformed_attempts": len(malformed),
            "identical_response_hashes": sorted(set(
                item.get("raw_sha256") for item in malformed
            )),
            "finish_reasons": [
                item.get("finish_reason") for item in malformed
            ],
            "parse_errors": [
                item.get("parse_error") for item in malformed
            ],
            "complete_first_malformed_response": complete_example
        }

    finally:
        conn.close()

    # Compact training measurements instead of full transcripts.
    training_summary = {}

    for task_id in sorted(ALLOWED_TASKS):
        subset = [r for r in training_traces if r["task_id"] == task_id]
        training_summary[task_id] = {
            "runs": len(subset),
            "verified_successes": sum(bool(r["verified_success"]) for r in subset),
            "mean_steps": round(
                sum(r["steps"] for r in subset) / len(subset), 2
            ),
            "mean_tokens": round(
                sum(r["total_tokens"] for r in subset) / len(subset), 2
            ),
            "malformed_json_responses": sum(
                item.get("error") == "bad json"
                for r in subset for item in r["trace"]
            ),
        }

    evidence = {
        "approved_training_tasks": sorted(ALLOWED_TASKS),
        "training_summary": training_summary,
        "diagnostic_reproduction": diagnostic_evidence
    }

    system_message = """You are NOVA-Genesis, a prompt-evolution researcher.

Your task is to propose a small improvement to NOVA's system prompt.

You are optimizing reliable structured tool-action generation.

Study the provided successful and malformed execution traces.
Identify recurring weaknesses and propose concise instructions that
could reduce malformed JSON responses.

STRICT CONSTRAINTS:

1. You may improve instructions, not Python code.
2. Do not invent new tools or actions.
3. Preserve the existing action interface.
4. Do not instruct NOVA to read or modify hidden tests.
5. Do not instruct NOVA to execute shell commands or Python.
6. Do not remove existing safety restrictions.
7. Do not make task-specific fixes for InventoryBatch.
8. Focus on reusable structured-output behavior.
9. Keep additions concise and operational.
10. Do not claim that a proposed improvement has been proven.
11. The proposed addition must contain no more than 100 words.

The original V0 prompt is immutable. You must propose only an
ADDENDUM to append to it, not rewrite or replace it.

Return your proposed prompt additions between these exact markers:

<<<NOVA_GENESIS_ADDITION_BEGIN>>>
Your proposed additional system-prompt instructions.
<<<NOVA_GENESIS_ADDITION_END>>>

Return no other content."""

    user_message = (
        "IMMUTABLE PARENT PROMPT V0:\n"
        + v0
        + "\n\nAPPROVED TRAINING EVIDENCE:\n"
        + json.dumps(evidence, indent=2)
        + "\n\nPropose the smallest useful reusable prompt addendum."
    )

    settings = get_settings()
    client = ModelClient(settings)

    try:
        response, usage, status = client.chat_with_usage(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            seed=0,
            max_tokens=512,
            reasoning_effort="none"
        )
    finally:
        client.close()

    # Preserve the exact generator response before attempting extraction.
    RAW_PATH.write_text(response, encoding="utf-8")

    metadata = {
        "generation": 1,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.model,
        "parent_prompt": "v0.txt",
        "parent_sha256": parent_hash,
        "generator_prompt_tokens": usage.get("prompt_tokens"),
        "generator_completion_tokens": usage.get("completion_tokens"),
        "generator_total_tokens": usage.get("total_tokens"),
        "generator_usage_complete": usage.get("usage_complete"),
        "generator_finish_reason": usage.get("finish_reason"),
        "generator_response_sha256": digest(response),
        "training_tasks": sorted(ALLOWED_TASKS),
        "training_run_count": len(training_traces),
        "diagnostic_run_id": DIAGNOSTIC_RUN_ID,
        "candidate_status": "not_generated"
    }

    if status != "success":
        META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        raise RuntimeError(f"Prompt generation failed: {status}")

    if not usage.get("usage_complete"):
        META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        raise RuntimeError("Generation token accounting incomplete.")

    if usage.get("finish_reason") == "length":
        META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        raise RuntimeError("Generation response hit its output limit.")

    if BEGIN_MARKER not in response or END_MARKER not in response:
        META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        raise RuntimeError("Candidate markers missing. No candidate promoted.")

    addition = response.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0].strip()

    if len(addition) < 50 or len(addition) > 1500:
        META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        raise RuntimeError("Candidate addendum has invalid length.")

    candidate = v0.rstrip() + "\n\n" + addition + "\n"

    # The original V0 must remain completely unchanged.
    if not candidate.startswith(v0.rstrip()):
        raise RuntimeError("Parent prompt preservation failed.")

    # Reject invented action schemas.
    import re

    original_actions = set(re.findall(
        r'"action"\s*:\s*"([^"]+)"', v0
    ))

    candidate_actions = set(re.findall(
        r'"action"\s*:\s*"([^"]+)"', candidate
    ))

    invented = candidate_actions - original_actions

    if invented:
        raise RuntimeError(f"Candidate introduced unsupported actions: {invented}")

    OUTPUT_PATH.write_text(candidate, encoding="utf-8")

    metadata.update({
        "candidate_status": "generated_not_promoted",
        "candidate_file": str(OUTPUT_PATH.relative_to(ROOT)),
        "candidate_sha256": digest(candidate),
        "candidate_characters": len(candidate),
        "addition_characters": len(addition)
    })

    META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n=== NOVA-GENESIS GENERATION 1 ===")
    print("Candidate:", OUTPUT_PATH)
    print("Parent SHA256:", parent_hash)
    print("Candidate SHA256:", digest(candidate))
    print("Generator tokens:", usage["total_tokens"])
    print("Finish reason:", usage.get("finish_reason"))
    print("Candidate status: NOT PROMOTED")
    print("\n=== PROPOSED ADDENDUM ===\n")
    print(addition)


if __name__ == "__main__":
    main()
