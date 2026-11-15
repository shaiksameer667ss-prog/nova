from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "eval" / "diagnostics"))

from adaptive_planning_pilot import EXPECTED, TASK, run_trial

from nova.controller.loop import SYSTEM_PROMPT

MODELS = ("qwen3.5:4b-8k", "qwen3.5:9b-8k")
OLLAMA_URL = "http://127.0.0.1:11434"


def model_digest(model: str) -> str:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()

    models = response.json().get("models", [])
    match = next((item for item in models if item.get("name") == model), None)

    if match is None:
        raise RuntimeError(f"Model is not installed in Ollama: {model}")

    digest = match.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError(f"Missing or invalid digest for {model}")

    return digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the NOVA-IL-001 paired reasoning feasibility pilot."
    )
    parser.add_argument("--model", choices=MODELS, default="qwen3.5:4b-8k")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.seed < 0:
        raise ValueError("Seed must be non-negative.")

    digest = model_digest(args.model)

    output_root = Path.home() / "nova-eval-lab" / "intelligence-lab-001"
    output_root.mkdir(parents=True, exist_ok=True)

    experiment_id = (
        "NOVA-IL-001-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    experiment_root = output_root / experiment_id
    experiment_root.mkdir(exist_ok=False)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    report = {
        "experiment": "NOVA-IL-001",
        "classification": "single-task exploratory feasibility pilot",
        "status": "running",
        "experiment_id": experiment_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_commit": commit,
        "python_version": platform.python_version(),
        "provider": "local Ollama",
        "ollama_url": OLLAMA_URL,
        "model": args.model,
        "model_digest": digest,
        "seed": args.seed,
        "temperature": 0.2,
        "max_steps": 8,
        "task_sha256": hashlib.sha256(TASK.encode()).hexdigest(),
        "expected_output_sha256": hashlib.sha256(
            EXPECTED.encode()
        ).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(
            SYSTEM_PROMPT.encode()
        ).hexdigest(),
        "fault_injection": "one transient tool-dispatch failure per condition",
        "conditions": {
            "A0": "existing controller; planning disabled",
            "A1": "existing controller; adaptive planning enabled",
        },
        "trials": {},
    }

    report_path = experiment_root / "report.json"

    def save_report() -> None:
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    save_report()

    for label, planning in (("A0", False), ("A1", True)):
        print(f"Running {label}: planning={planning}")

        result = run_trial(
            args.model,
            args.seed,
            planning,
            experiment_root,
        )

        report["trials"][label] = result
        save_report()

        print(
            f"{label}: verified={result['independently_verified_success']}, "
            f"claimed={result['agent_success']}, "
            f"tokens={result['total_tokens']}, "
            f"steps={result['steps']}"
        )

    report["status"] = "completed"
    save_report()

    print("\nExperiment:", experiment_id)
    print("Model digest:", digest)
    print("Report:", report_path)
    print("Classification: exploratory pilot, not general intelligence evidence")


if __name__ == "__main__":
    main()
