"""Internal repair-candidate generation for the NOVA controller.

Bridges the controller to the BASE+V6 candidate generator
(Qwen2.5-Coder-7B-Instruct + LoRA v6) that lives in the evaluation lab.
Transport is isolated in _generate_via_bridge. Until configured, this
fails closed and the controller continues without a candidate.
Returns {"error": "<reason>"} on any failure; never raises.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

BRIDGE_TIMEOUT_SECONDS = 300


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bridge_command() -> list[str] | None:
    raw = os.environ.get("NOVA_CANDIDATE_BRIDGE_CMD", "").strip()
    if not raw:
        return None
    try:
        cmd = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(cmd, list) or not cmd:
        return None
    if not all(isinstance(p, str) for p in cmd):
        return None
    return cmd


def _generate_via_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    cmd = _bridge_command()
    if cmd is None:
        return {
            "error": (
                "candidate bridge not configured "
                "(NOVA_CANDIDATE_BRIDGE_CMD unset or malformed)"
            )
        }
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=BRIDGE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"bridge invocation failed: {type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"error": f"bridge exited {proc.returncode}: {proc.stderr.strip()[:500]}"}
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"bridge returned non-JSON output: {exc}"}
    if not isinstance(result, dict) or not isinstance(result.get("content"), str):
        return {"error": "bridge returned no candidate content"}
    return result


def generate_candidate(
    path: str,
    task_context: str,
    workspace: Path,
    settings: Any,
) -> dict[str, Any]:
    try:
        root = Path(workspace).resolve()
        source_path = (root / path).resolve()
        source_path.relative_to(root)
    except (OSError, ValueError):
        return {"error": f"path outside workspace: {path!r}"}
    if not source_path.is_file():
        return {"error": f"source file not found: {path}"}
    try:
        broken_source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"cannot read {path}: {exc}"}
    result = _generate_via_bridge({
        "path": path,
        "broken_source": broken_source,
        "task_context": task_context,
    })
    if result.get("error"):
        return result
    content = result["content"]
    return {
        "path": path,
        "content": content,
        "model_id": result.get("model_id", "unknown"),
        "adapter_id": result.get("adapter_id"),
        "adapter_sha256": result.get("adapter_sha256"),
        "prompt_sha256": result.get("prompt_sha256"),
        "selected_source": result.get("selected_source"),
        "selected_sha256": result.get("selected_sha256"),
        "trial_dir": result.get("trial_dir"),
        "generation_config": result.get("generation_config", {}),
        "candidate_source": "internal",
        "generated_source_sha256": _sha256(content),
        "broken_source_sha256": _sha256(broken_source),
    }