"""Restricted behavioral probes using NOVA's rootless WSL Docker sandbox."""

from __future__ import annotations

import ast
import json
import math
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


class BehavioralProbeError(ValueError):
    '''Invalid or unsuccessful behavioral probe.'''

def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise BehavioralProbeError('Invalid relative Python path.')
    path = PurePosixPath(value)
    forbidden = {'verifier', 'reference', '__pycache__', 'hidden_tests', '.env', '.git', '.venv'}
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or path.suffix != '.py' or forbidden.intersection(path.parts):
        raise BehavioralProbeError('Probe path is not permitted.')
    return value

def _validate_json_value(value: Any, depth: int=0) -> None:
    if depth > 12:
        raise BehavioralProbeError('Probe JSON nesting exceeds 12 levels.')
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BehavioralProbeError('Probe numbers must be finite.')
        return
    if isinstance(value, list):
        if len(value) > 256:
            raise BehavioralProbeError('Probe array is too large.')
        for item in value:
            _validate_json_value(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 256:
            raise BehavioralProbeError('Probe object is too large.')
        for key, item in value.items():
            if not isinstance(key, str):
                raise BehavioralProbeError('Probe object keys must be strings.')
            _validate_json_value(item, depth + 1)
        return
    raise BehavioralProbeError('Probe values must be JSON-compatible.')


def serialize_typed_record(record_spec: Any) -> str:
    """Serialize typed key/value fields into the CFD-001 record grammar."""
    if not isinstance(record_spec, dict) or set(record_spec) != {"fields"}:
        raise BehavioralProbeError("Typed record must contain only fields.")
    fields = record_spec["fields"]
    if not isinstance(fields, list) or not 1 <= len(fields) <= 32:
        raise BehavioralProbeError("Typed record requires 1 to 32 fields.")

    serialized_fields = []
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"key", "type", "value"}:
            raise BehavioralProbeError(
                "Typed record fields require key, type, and value."
            )
        key = field["key"]
        value_type = field["type"]
        value = field["value"]
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 100
            or any(char in key for char in (";", "=", '"', "\\", "\x00"))
        ):
            raise BehavioralProbeError("Typed record contains an invalid field key.")
        if (
            not isinstance(value_type, str)
            or value_type not in {"quoted", "unquoted"}
        ):
            raise BehavioralProbeError(
                "Typed record value type must be quoted or unquoted."
            )
        if not isinstance(value, str) or len(value) > 4000:
            raise BehavioralProbeError(
                "Typed record values must be strings of at most 4000 characters."
            )

        if value_type == "quoted":
            encoded_value = json.dumps(value, ensure_ascii=False)
        else:
            if ";" in value or '"' in value:
                raise BehavioralProbeError(
                    "Unquoted typed values cannot contain semicolons or double quotes."
                )
            encoded_value = value
        serialized_fields.append(f"{key}={encoded_value}")

    return ";".join(serialized_fields)


def validate_behavioral_probe(
    observed_files: dict[str, str],
    probe: dict[str, Any],
    *,
    allow_typed_record: bool = False,
) -> dict[str, Any]:
    """Validate a structured call to an observed public Python function."""
    if not isinstance(observed_files, dict) or not isinstance(probe, dict):
        raise BehavioralProbeError("Invalid behavioral probe input.")

    legacy_required = {
        "kind", "path", "function", "args", "kwargs", "expected_result"
    }
    required = legacy_required | {"expected_exception"}
    if (
        set(probe) not in (legacy_required, required)
        or probe.get("kind") != "function_call"
    ):
        raise BehavioralProbeError("Invalid behavioral probe fields.")

    expected_exception = probe.get("expected_exception")
    if expected_exception is not None:
        if (
            not isinstance(expected_exception, dict)
            or set(expected_exception) != {"type", "message"}
        ):
            raise BehavioralProbeError("Invalid expected exception.")
        exception_type = expected_exception["type"]
        exception_message = expected_exception["message"]
        if (
            not isinstance(exception_type, str)
            or not exception_type.isidentifier()
            or exception_type.startswith("_")
            or len(exception_type) > 100
            or not isinstance(exception_message, str)
            or len(exception_message) > 1000
        ):
            raise BehavioralProbeError("Invalid expected exception.")
        if probe["expected_result"] is not None:
            raise BehavioralProbeError(
                "Expected exceptions require expected_result to be null."
            )

    path = _safe_path(probe["path"])
    function = probe["function"]
    if (
        not isinstance(function, str)
        or not function.isidentifier()
        or function.startswith("_")
    ):
        raise BehavioralProbeError("Only public Python functions are permitted.")

    args = probe["args"]
    kwargs = probe["kwargs"]
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise BehavioralProbeError("Probe args/kwargs have invalid types.")
    if len(args) > 16 or len(kwargs) > 16:
        raise BehavioralProbeError("Probe has too many arguments.")

    if not isinstance(allow_typed_record, bool):
        raise BehavioralProbeError("allow_typed_record must be a boolean.")
    if (
        allow_typed_record
        and len(args) == 1
        and isinstance(args[0], dict)
        and set(args[0]) == {"fields"}
    ):
        args = [serialize_typed_record(args[0])]

    if any(
        not isinstance(key, str)
        or not key.isidentifier()
        or key.startswith("_")
        for key in kwargs
    ):
        raise BehavioralProbeError("Invalid keyword argument name.")

    _validate_json_value(args)
    _validate_json_value(kwargs)
    _validate_json_value(probe["expected_result"])

    files: dict[str, str] = {}
    total_bytes = 0
    for name, file_source in observed_files.items():
        if not isinstance(name, str) or not name.endswith(".py"):
            continue
        safe_name = _safe_path(name)
        if not isinstance(file_source, str):
            raise BehavioralProbeError("Observed Python source must be text.")
        file_source = file_source.removeprefix("\ufeff")
        total_bytes += len(file_source.encode("utf-8"))
        files[safe_name] = file_source

    if path not in files:
        raise BehavioralProbeError("Probe source must have been observed.")
    if len(files) > 6 or total_bytes > 18000:
        raise BehavioralProbeError("Observed source exceeds probe limits.")

    try:
        tree = ast.parse(files[path], filename=path)
    except SyntaxError as exc:
        raise BehavioralProbeError(
            f"Observed source has invalid syntax: {exc.msg}"
        ) from exc

    if not any(
        isinstance(node, ast.FunctionDef) and node.name == function
        for node in tree.body
    ):
        raise BehavioralProbeError(
            "Requested public synchronous function was not found."
        )

    normalized = {
        "kind": "function_call",
        "path": path,
        "function": function,
        "args": args,
        "kwargs": kwargs,
        "expected_result": probe["expected_result"],
        "expected_exception": expected_exception,
        "observed_python_files": files,
    }
    encoded = json.dumps(
        normalized, ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(encoded) > 30000:
        raise BehavioralProbeError("Complete probe payload exceeds 30 KiB.")
    return normalized

_CONTAINER_HARNESS = '\nimport contextlib\nimport importlib.util\nimport io\nimport json\nimport sys\nfrom pathlib import Path\n\nsys.dont_write_bytecode = True\nroot = Path("/workspace").resolve()\nprobe = json.loads((root / "_nova_probe.json").read_text(encoding="utf-8"))\ntarget = (root / probe["path"]).resolve()\n\nif not target.is_relative_to(root) or not target.is_file():\n    raise RuntimeError("Probe target is outside the staged workspace")\n\nsys.path.insert(0, str(root))\nsys.path.insert(0, str(target.parent))\ncaptured = io.StringIO()\n\ntry:\n    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):\n        spec = importlib.util.spec_from_file_location(\n            "_nova_observed_module", target\n        )\n        if spec is None or spec.loader is None:\n            raise ImportError("Could not load observed module")\n        module = importlib.util.module_from_spec(spec)\n        sys.modules[spec.name] = module\n        spec.loader.exec_module(module)\n        function = getattr(module, probe["function"], None)\n        if not callable(function):\n            raise AttributeError("Requested function is not callable")\nexcept Exception as exc:\n    execution = {\n        "harness_ok": False,\n        "harness_error_type": type(exc).__name__,\n        "harness_error": str(exc)[:1000],\n    }\nelse:\n    try:\n        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):\n            actual = function(*probe["args"], **probe["kwargs"])\n            actual = json.loads(json.dumps(\n                actual, ensure_ascii=False, allow_nan=False\n            ))\n        execution = {"harness_ok": True, "actual": actual}\n    except Exception as exc:\n        execution = {\n            "harness_ok": True,\n            "raised": {\n                "type": type(exc).__name__,\n                "message": str(exc)[:1000],\n            },\n        }\n\nexecution["captured_output"] = captured.getvalue()[:3000]\nprint("NOVA_BHT_FUNCTION_RESULT:" + json.dumps(execution, ensure_ascii=False))\n'
_WSL_BOOTSTRAP = '\nimport json\nimport sys\nimport tempfile\nfrom pathlib import Path\n\nMARKER = "NOVA_BHT_RESULT:"\n\ntry:\n    sys.dont_write_bytecode = True\n    source_root = sys.argv[1]\n    sys.path.insert(0, source_root)\n\n    from nova.tools.docker_sandbox import DockerSandboxRunner, SandboxLimits\n\n    payload = json.load(sys.stdin)\n    root = Path.home() / "nova-eval-lab" / "workspaces"\n    root.mkdir(parents=True, exist_ok=True)\n\n    with tempfile.TemporaryDirectory(prefix="nova-bht-", dir=root) as temp:\n        workspace = Path(temp).resolve()\n\n        for relative, source in payload["observed_python_files"].items():\n            target = (workspace / relative).resolve()\n            if not target.is_relative_to(workspace):\n                raise ValueError("Unsafe staged source path")\n            target.parent.mkdir(parents=True, exist_ok=True)\n            target.write_text(source, encoding="utf-8")\n            target.chmod(0o644)\n\n        (workspace / "_nova_probe.json").write_text(\n            json.dumps(payload["probe"], ensure_ascii=False, allow_nan=False),\n            encoding="utf-8",\n        )\n        (workspace / "_nova_behavior_probe.py").write_text(\n            payload["harness"], encoding="utf-8"\n        )\n\n        for item in workspace.rglob("*"):\n            if item.is_dir():\n                item.chmod(0o755)\n        workspace.chmod(0o755)\n\n        runner = DockerSandboxRunner(\n            root,\n            limits=SandboxLimits(\n                timeout_seconds=8,\n                max_output_bytes=65536,\n            ),\n        )\n        result = runner.run(\n            workspace,\n            ["python", "-B", "_nova_behavior_probe.py"],\n            timeout_seconds=8,\n        )\n\n        response = {\n            "sandbox_succeeded": result.succeeded,\n            "exit_code": result.exit_code,\n            "stdout": result.stdout,\n            "stderr": result.stderr[:3000],\n            "timed_out": result.timed_out,\n            "output_limited": result.output_limited,\n            "duration_seconds": result.duration_seconds,\n        }\n        print(MARKER + json.dumps(response, ensure_ascii=False))\nexcept Exception as exc:\n    print(MARKER + json.dumps({\n        "bridge_error": type(exc).__name__ + ": " + str(exc)\n    }, ensure_ascii=False))\n'

def run_behavioral_probe(observed_files: dict[str, str], probe: dict[str, Any], source_root: Path | None=None, *, wsl_distribution: str='Ubuntu-24.04') -> dict[str, Any]:
    '''Run one structured observed-function call in the rootless Docker sandbox.'''

    normalized = validate_behavioral_probe(observed_files, probe)
    if source_root is None:
        source_root = Path(__file__).resolve().parents[2]
    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise BehavioralProbeError('NOVA source directory does not exist.')
    windows_path = str(source_root).replace('\\', '/')
    try:
        converted = subprocess.run(['wsl.exe', '-d', wsl_distribution, '--', 'wslpath', '-u', windows_path], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BehavioralProbeError(f'WSL path conversion failed: {exc}') from exc
    linux_source = converted.stdout.strip()
    if converted.returncode != 0 or not linux_source:
        raise BehavioralProbeError(f'WSL path conversion failed: {converted.stderr.strip()}')
    payload = json.dumps({'observed_python_files': normalized['observed_python_files'], 'probe': {key: normalized[key] for key in ('path', 'function', 'args', 'kwargs', 'expected_result', 'expected_exception')}, 'harness': _CONTAINER_HARNESS}, ensure_ascii=False, allow_nan=False)
    bootstrap = _WSL_BOOTSTRAP.replace('    payload = json.load(sys.stdin)', f'    payload = json.loads({payload!r})', 1).replace('    source_root = sys.argv[1]', f'    source_root = {linux_source!r}', 1)
    try:
        completed = subprocess.run(['wsl.exe', '-d', wsl_distribution, '--', 'python3', '-'], input=bootstrap, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BehavioralProbeError(f'Behavioral sandbox bridge failed: {exc}') from exc
    marker = 'NOVA_BHT_RESULT:'
    records = [line[len(marker):] for line in completed.stdout.splitlines() if line.startswith(marker)]
    if completed.returncode != 0 or not records:
        raise BehavioralProbeError('Sandbox bridge returned no result: ' + completed.stderr[-2000:])
    try:
        bridge = json.loads(records[-1])
    except json.JSONDecodeError as exc:
        raise BehavioralProbeError('Invalid sandbox bridge response.') from exc
    if 'bridge_error' in bridge:
        raise BehavioralProbeError(bridge['bridge_error'])
    if not bridge.get('sandbox_succeeded'):
        return {'verdict': 'INCONCLUSIVE', 'evidence_kind': 'sandbox_execution', 'reason': bridge.get('stderr') or 'Sandbox execution failed.', 'causality_established': False, 'sandbox': bridge}
    function_marker = 'NOVA_BHT_FUNCTION_RESULT:'
    function_records = [line[len(function_marker):] for line in bridge.get('stdout', '').splitlines() if line.startswith(function_marker)]
    if not function_records:
        return {'verdict': 'INCONCLUSIVE', 'evidence_kind': 'sandbox_execution', 'reason': 'Function harness returned no structured result.', 'causality_established': False, 'sandbox': bridge}
    try:
        execution = json.loads(function_records[-1])
    except json.JSONDecodeError:
        return {'verdict': 'INCONCLUSIVE', 'evidence_kind': 'sandbox_execution', 'reason': 'Function harness returned invalid JSON.', 'causality_established': False, 'sandbox': bridge}
    if not execution.get('harness_ok'):
        return {'verdict': 'INCONCLUSIVE', 'evidence_kind': 'sandbox_execution', 'reason': execution.get('harness_error'), 'error_type': execution.get('harness_error_type'), 'causality_established': False}
    if 'raised' in execution:
        actual_exception = execution['raised']
        expected_exception = normalized['expected_exception']
        matched = expected_exception is not None and actual_exception.get('type') == expected_exception['type'] and actual_exception.get('message') == expected_exception['message']
        return {'verdict': 'PREDICTION_MATCHED' if matched else 'PREDICTION_MISMATCHED', 'probe_kind': 'function_call', 'path': normalized['path'], 'function': normalized['function'], 'expected_result': normalized['expected_result'], 'expected_exception': expected_exception, 'actual_exception': actual_exception, 'prediction_matched': matched, 'probe_completed': True, 'evidence_kind': 'sandbox_execution', 'causality_established': False, 'sandbox_duration_seconds': bridge.get('duration_seconds')}
    def canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

    actual = execution['actual']
    expected = normalized['expected_result']
    expected_exception = normalized['expected_exception']
    matched = expected_exception is None and canonical(actual) == canonical(expected)
    return {'verdict': 'PREDICTION_MATCHED' if matched else 'PREDICTION_MISMATCHED', 'probe_kind': 'function_call', 'path': normalized['path'], 'function': normalized['function'], 'expected_result': expected, 'expected_exception': expected_exception, 'actual_result': actual, 'prediction_matched': matched, 'probe_completed': True, 'captured_output': execution.get('captured_output', ''), 'evidence_kind': 'sandbox_execution', 'causality_established': False, 'sandbox_duration_seconds': bridge.get('duration_seconds')}

