from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


class AcceptanceSandboxError(RuntimeError):
    """The candidate call could not be executed or observed reliably."""


_BRIDGE_MARKER = "NOVA_ACCEPTANCE_BRIDGE:"
_RESULT_MARKER = "NOVA_ACCEPTANCE_CALL:"
_MAX_SOURCE_FILES = 128
_MAX_SOURCE_BYTES = 2_000_000
_MAX_CASE_BYTES = 64_000

_ALLOWED_EXCEPTION_NAMES = {
    "ArithmeticError", "AssertionError", "AttributeError",
    "ConnectionError", "EOFError", "Exception", "ImportError",
    "IndexError", "KeyError", "LookupError", "NameError",
    "NotImplementedError", "OSError", "OverflowError",
    "RuntimeError", "StopIteration", "TimeoutError", "TypeError",
    "ValueError", "ZeroDivisionError",
}


def _normalize_sources(sources: dict[str, str]) -> dict[str, str]:
    if not isinstance(sources, dict) or not sources:
        raise AcceptanceSandboxError("No candidate source files were supplied.")
    if len(sources) > _MAX_SOURCE_FILES:
        raise AcceptanceSandboxError("Too many candidate source files.")

    normalized: dict[str, str] = {}
    total_bytes = 0

    for raw_name, source in sources.items():
        if not isinstance(raw_name, str) or not isinstance(source, str):
            raise AcceptanceSandboxError("Candidate source entries must be strings.")

        name = raw_name.replace("\\", "/")
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or ":" in path.parts[0]
            or "\x00" in name
            or path.suffix.lower() != ".py"
        ):
            raise AcceptanceSandboxError(
                f"Unsafe or unsupported candidate source path: {raw_name!r}"
            )

        canonical = path.as_posix()
        if canonical in normalized:
            raise AcceptanceSandboxError(f"Duplicate candidate source path: {canonical}")

        total_bytes += len(source.encode("utf-8"))
        if total_bytes > _MAX_SOURCE_BYTES:
            raise AcceptanceSandboxError("Candidate source set exceeds the size limit.")
        normalized[canonical] = source

    return normalized


def _validate_case_value(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise AcceptanceSandboxError("Acceptance input nesting exceeds 12 levels.")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AcceptanceSandboxError("Acceptance numbers must be finite.")
        return
    if isinstance(value, list):
        if len(value) > 256:
            raise AcceptanceSandboxError("Acceptance array is too large.")
        for item in value:
            _validate_case_value(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 256 or any(not isinstance(key, str) for key in value):
            raise AcceptanceSandboxError("Invalid acceptance object.")

        descriptor = value.get("$nova_acceptance")
        if descriptor == "sequence_callable":
            if set(value) != {"$nova_acceptance", "name", "steps"}:
                raise AcceptanceSandboxError("Invalid sequence_callable fields.")
            name = value["name"]
            steps = value["steps"]
            if (
                not isinstance(name, str)
                or not name.isidentifier()
                or not isinstance(steps, list)
                or not 1 <= len(steps) <= 64
            ):
                raise AcceptanceSandboxError("Invalid sequence_callable descriptor.")

            for step in steps:
                if not isinstance(step, dict):
                    raise AcceptanceSandboxError("Invalid sequence step.")
                action = step.get("action")
                if action == "return" and set(step) == {"action", "value"}:
                    _validate_case_value(step["value"], depth + 1)
                elif action == "raise" and set(step) == {
                    "action", "exception_type", "message"
                }:
                    exception_type = step["exception_type"]
                    message = step["message"]
                    if (
                        not isinstance(exception_type, str)
                        or exception_type not in _ALLOWED_EXCEPTION_NAMES
                        or not isinstance(message, str)
                        or len(message) > 1000
                    ):
                        raise AcceptanceSandboxError("Invalid sequence exception step.")
                else:
                    raise AcceptanceSandboxError("Unsupported sequence step.")
            return

        if descriptor == "recording_callable":
            if set(value) != {"$nova_acceptance", "name"}:
                raise AcceptanceSandboxError("Invalid recording_callable fields.")
            if not isinstance(value["name"], str) or not value["name"].isidentifier():
                raise AcceptanceSandboxError("Invalid recording_callable name.")
            return

        if descriptor == "exception_types":
            if set(value) != {"$nova_acceptance", "items"}:
                raise AcceptanceSandboxError("Invalid exception_types fields.")
            items = value["items"]
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 16
                or any(
                    not isinstance(name, str)
                    or name not in _ALLOWED_EXCEPTION_NAMES
                    for name in items
                )
                or len(set(items)) != len(items)
            ):
                raise AcceptanceSandboxError("Unsupported exception_types descriptor.")
            return

        if "$nova_acceptance" in value:
            raise AcceptanceSandboxError("Unknown acceptance descriptor.")

        for item in value.values():
            _validate_case_value(item, depth + 1)
        return

    raise AcceptanceSandboxError(
        f"Unsupported acceptance input type: {type(value).__name__}"
    )


_CONTAINER_HARNESS = r'''
import builtins
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
root = Path("/workspace").resolve()
payload = json.load(sys.stdin)
capture = io.StringIO()
response = {}
traces = {}

_ALLOWED_NAMES = {
    "ArithmeticError", "AssertionError", "AttributeError",
    "ConnectionError", "EOFError", "Exception", "ImportError",
    "IndexError", "KeyError", "LookupError", "NameError",
    "NotImplementedError", "OSError", "OverflowError",
    "RuntimeError", "StopIteration", "TimeoutError", "TypeError",
    "ValueError", "ZeroDivisionError",
}
_ALLOWED_EXCEPTIONS = {
    name: getattr(builtins, name)
    for name in _ALLOWED_NAMES
}


def _json_safe(value):
    return json.loads(json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
    ))


def _resolve(value):
    if isinstance(value, list):
        return [_resolve(item) for item in value]
    if not isinstance(value, dict):
        return value

    descriptor = value.get("$nova_acceptance")

    if descriptor == "exception_types":
        return tuple(
            _ALLOWED_EXCEPTIONS[name]
            for name in value["items"]
        )

    if descriptor == "recording_callable":
        name = value["name"]
        trace = {"calls": []}

        def callback(*args, **kwargs):
            trace["calls"].append({
                "args": _json_safe(args),
                "kwargs": _json_safe(kwargs),
            })
            return None

        traces[name] = trace
        return callback

    if descriptor == "sequence_callable":
        name = value["name"]
        steps = value["steps"]
        trace = {"calls": [], "errors": []}
        index = 0

        def callback(*args, **kwargs):
            nonlocal index
            current = index
            index += 1
            trace["calls"].append({
                "args": _json_safe(args),
                "kwargs": _json_safe(kwargs),
            })

            if current >= len(steps):
                raise RuntimeError(
                    "Acceptance sequence callable exhausted: " + name
                )

            step = steps[current]
            if step["action"] == "return":
                return step["value"]

            exception_class = _ALLOWED_EXCEPTIONS[step["exception_type"]]
            exc = exception_class(step["message"])
            token = name + ":" + str(current)
            exc._nova_acceptance_token = token
            trace["errors"].append({
                "token": token,
                "type": type(exc).__name__,
                "message": str(exc),
            })
            raise exc

        traces[name] = trace
        return callback

    return {
        key: _resolve(item)
        for key, item in value.items()
    }


case = payload
target = (root / case["path"]).resolve()

if not target.is_relative_to(root) or not target.is_file():
    response = {
        "status": "candidate_error",
        "error_type": "FileNotFoundError",
        "error": "Requested candidate module is unavailable.",
    }
else:
    try:
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            sys.path.insert(0, str(root))
            sys.path.insert(0, str(target.parent))
            spec = importlib.util.spec_from_file_location(
                "_nova_acceptance_candidate",
                target,
            )
            if spec is None or spec.loader is None:
                raise ImportError("Could not load candidate module.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            function = getattr(module, case["function"], None)
            if not callable(function):
                raise AttributeError("Requested candidate function is not callable.")
    except BaseException as exc:
        response = {
            "status": "candidate_error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
        }
    else:
        try:
            args = _resolve(case["args"])
            kwargs = _resolve(case["kwargs"])
            with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
                result = function(*args, **kwargs)
            response = {
                "status": "returned",
                "result": _json_safe(result),
            }
        except BaseException as exc:
            response = {
                "status": "raised",
                "exception": {
                    "type": type(exc).__name__,
                    "message": str(exc)[:2000],
                    "token": getattr(exc, "_nova_acceptance_token", None),
                },
            }

        response["callables"] = traces

response["captured_output"] = capture.getvalue()[-2000:]
print("NOVA_ACCEPTANCE_CALL:" + json.dumps(response, ensure_ascii=False))
'''


_WSL_BOOTSTRAP = r'''
import json
import sys
import tempfile
from pathlib import Path

MARKER = "NOVA_ACCEPTANCE_BRIDGE:"

try:
    sys.dont_write_bytecode = True
    source_root = sys.argv[1]
    sys.path.insert(0, source_root)

    from nova.tools.docker_sandbox import DockerSandboxRunner, SandboxLimits

    payload = json.load(sys.stdin)
    root = Path.home() / "nova-eval-lab" / "workspaces"
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nova-acceptance-", dir=root) as temp:
        workspace = Path(temp).resolve()

        for relative, source in payload["sources"].items():
            target = (workspace / relative).resolve()
            if not target.is_relative_to(workspace):
                raise ValueError("Unsafe staged candidate source path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            target.chmod(0o644)

        harness = workspace / "_nova_acceptance_harness.py"
        harness.write_text(payload["harness"], encoding="utf-8")
        harness.chmod(0o644)

        for item in workspace.rglob("*"):
            if item.is_dir():
                item.chmod(0o755)
        workspace.chmod(0o755)

        runner = DockerSandboxRunner(
            root,
            limits=SandboxLimits(
                timeout_seconds=8,
                max_output_bytes=65536,
            ),
        )
        result = runner.run(
            workspace,
            ["python", "-B", "_nova_acceptance_harness.py"],
            stdin=json.dumps(payload["case"], ensure_ascii=False, allow_nan=False),
            timeout_seconds=8,
        )

        print(MARKER + json.dumps({
            "sandbox_succeeded": result.succeeded,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr[:3000],
            "timed_out": result.timed_out,
            "output_limited": result.output_limited,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False))

except Exception as exc:
    print(MARKER + json.dumps({
        "bridge_error": type(exc).__name__ + ": " + str(exc)
    }, ensure_ascii=False))
'''


def run_acceptance_call(
    sources: dict[str, str],
    *,
    target_path: str,
    function: str,
    args: list[Any],
    kwargs: dict[str, Any],
    source_root: Path | None = None,
    wsl_distribution: str = "Ubuntu-24.04",
) -> dict[str, Any]:
    """Execute one candidate call; trusted assertions remain on the host."""
    normalized = _normalize_sources(sources)

    if not isinstance(target_path, str):
        raise AcceptanceSandboxError("Candidate target path must be a string.")
    target_path = target_path.replace("\\", "/")
    target = PurePosixPath(target_path)

    if (
        target.is_absolute()
        or ".." in target.parts
        or target.suffix.lower() != ".py"
        or target_path not in normalized
    ):
        raise AcceptanceSandboxError(
            "Acceptance target must name a staged candidate Python file."
        )

    if not isinstance(function, str) or not function.isidentifier():
        raise AcceptanceSandboxError("Invalid candidate function name.")
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise AcceptanceSandboxError("Acceptance args/kwargs have invalid shapes.")
    if any(not isinstance(key, str) for key in kwargs):
        raise AcceptanceSandboxError("Acceptance keyword names must be strings.")

    _validate_case_value(args)
    _validate_case_value(kwargs)

    descriptor_names: list[str] = []

    def collect_descriptors(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect_descriptors(item)
        elif isinstance(value, dict):
            descriptor = value.get("$nova_acceptance")
            if descriptor in {"sequence_callable", "recording_callable"}:
                name = value["name"]
                if name in descriptor_names:
                    raise AcceptanceSandboxError(
                        f"Duplicate acceptance callback name: {name}"
                    )
                descriptor_names.append(name)
            else:
                for item in value.values():
                    collect_descriptors(item)

    collect_descriptors(args)
    collect_descriptors(kwargs)

    case = {
        "path": target_path,
        "function": function,
        "args": args,
        "kwargs": kwargs,
    }
    encoded_case = json.dumps(case, ensure_ascii=False, allow_nan=False)
    if len(encoded_case.encode("utf-8")) > _MAX_CASE_BYTES:
        raise AcceptanceSandboxError("Acceptance call payload exceeds the size limit.")

    if source_root is None:
        source_root = Path(__file__).resolve().parents[2]
    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise AcceptanceSandboxError("NOVA source directory does not exist.")

    try:
        converted = subprocess.run(
            [
                "wsl.exe", "-d", wsl_distribution, "--",
                "wslpath", "-u",
                str(source_root).replace("\\", "/"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceSandboxError(
            f"WSL path conversion failed: {type(exc).__name__}: {exc}"
        ) from exc

    linux_source = converted.stdout.strip()
    if converted.returncode != 0 or not linux_source:
        raise AcceptanceSandboxError(
            "WSL path conversion failed: " + converted.stderr.strip()[:1000]
        )

    payload = {
        "sources": normalized,
        "harness": _CONTAINER_HARNESS,
        "case": case,
    }
    encoded_payload = json.dumps(payload, ensure_ascii=False, allow_nan=False)

    bootstrap = (
        _WSL_BOOTSTRAP
        .replace(
            "    payload = json.load(sys.stdin)",
            f"    payload = json.loads({encoded_payload!r})",
            1,
        )
        .replace(
            "    source_root = sys.argv[1]",
            f"    source_root = {linux_source!r}",
            1,
        )
    )

    try:
        completed = subprocess.run(
            ["wsl.exe", "-d", wsl_distribution, "--", "python3", "-"],
            input=bootstrap,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceSandboxError(
            f"Acceptance sandbox bridge failed: {type(exc).__name__}: {exc}"
        ) from exc

    records = [
        line[len(_BRIDGE_MARKER):]
        for line in completed.stdout.splitlines()
        if line.startswith(_BRIDGE_MARKER)
    ]
    if completed.returncode != 0 or len(records) != 1:
        raise AcceptanceSandboxError(
            "Acceptance sandbox bridge returned no unique result: "
            + completed.stderr[-2000:]
        )

    try:
        bridge = json.loads(records[0])
    except json.JSONDecodeError as exc:
        raise AcceptanceSandboxError(
            "Acceptance sandbox bridge returned invalid JSON."
        ) from exc

    if "bridge_error" in bridge:
        raise AcceptanceSandboxError(bridge["bridge_error"])
    if bridge.get("sandbox_succeeded") is not True:
        raise AcceptanceSandboxError(
            "Acceptance sandbox did not complete: "
            + str(bridge.get("stderr") or bridge.get("exit_code"))
        )

    call_records = [
        line[len(_RESULT_MARKER):]
        for line in bridge.get("stdout", "").splitlines()
        if line.startswith(_RESULT_MARKER)
    ]
    if len(call_records) != 1:
        raise AcceptanceSandboxError(
            "Candidate call returned no unique structured observation."
        )

    try:
        observation = json.loads(call_records[0])
    except json.JSONDecodeError as exc:
        raise AcceptanceSandboxError(
            "Candidate call returned invalid observation JSON."
        ) from exc

    observation["sandbox_duration_seconds"] = bridge.get("duration_seconds")
    return observation
