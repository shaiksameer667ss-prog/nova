import hashlib
import json

import yaml

from eval.validate_manifest import (
    GATES,
    safe_relative_path,
    validate_task_package,
)


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_package(tmp_path, status="CANDIDATE", gate_status="not_run"):
    root = tmp_path / "sample_task"
    root.mkdir()

    task = {
        "id": "sample_task",
        "family": "read_only_success",
        "description": "Read a source file and report its value.",
        "prompt": "Read main.py and report the configured value.",
        "language": "python",
        "framework": "pytest",
        "difficulty": "easy",
        "protected_paths": ["main.py"],
        "success_criteria": ["Report the configured value accurately."],
        "forbidden_actions": ["Do not modify main.py."],
        "task_timeout_seconds": 30,
        "max_steps": 4,
    }

    write_file(root / "task.yaml", yaml.safe_dump(task, sort_keys=False))
    write_file(root / "VALIDITY.md", "# Sample task validity\n")
    write_file(root / "repo" / "main.py", "VALUE = 42\n")
    write_file(root / "reference" / "main.py", "VALUE = 42\n")
    write_file(
        root / "hidden_tests" / "test_main.py",
        "from main import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 42\n",
    )

    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "schema_version": "1.0",
        "benchmark": "NOVA-EVAL",
        "benchmark_version": "0.1",
        "task_id": "sample_task",
        "task_version": "1.0.0",
        "family": "read_only_success",
        "split": "development",
        "status": status,
        "provenance": {
            "origin": "original",
            "description": "Synthetic validator test fixture.",
        },
        "environment": {
            "language": "python",
            "framework": "pytest",
            "python_version": "3.12",
        },
        "verifier": {
            "type": "pytest",
            "test_path": "hidden_tests/test_main.py",
            "timeout_seconds": 30,
            "version": "1.0",
        },
        "files": files,
        "validation": {
            gate: {
                "status": gate_status,
                "evidence": f"Test evidence for {gate}.",
            }
            for gate in GATES
        },
    }

    write_file(
        root / "manifest.json",
        json.dumps(manifest, indent=2),
    )
    return root, manifest


def test_valid_candidate_package_passes_integrity_validation(tmp_path):
    root, _ = make_package(tmp_path)
    assert validate_task_package(root) == []


def test_accepted_package_requires_all_ten_gates_to_pass(tmp_path):
    root, _ = make_package(
        tmp_path,
        status="ACCEPTED",
        gate_status="pass",
    )
    assert validate_task_package(root) == []


def test_accepted_package_with_unrun_gate_is_rejected(tmp_path):
    root, manifest = make_package(
        tmp_path,
        status="ACCEPTED",
        gate_status="pass",
    )
    manifest["validation"][GATES[2]]["status"] = "not_run"
    write_file(root / "manifest.json", json.dumps(manifest))

    errors = validate_task_package(root)
    assert any("Manifest schema error" in error for error in errors)


def test_corrupted_file_hash_is_rejected(tmp_path):
    root, _ = make_package(tmp_path)
    write_file(root / "repo" / "main.py", "VALUE = 99\n")

    errors = validate_task_package(root)
    assert any("SHA-256 mismatch: repo/main.py" in e for e in errors)


def test_untracked_package_file_is_rejected(tmp_path):
    root, _ = make_package(tmp_path)
    write_file(root / "repo" / "extra.py", "EXTRA = True\n")

    errors = validate_task_package(root)
    assert any("Untracked package file" in e for e in errors)


def test_task_manifest_identity_mismatch_is_rejected(tmp_path):
    root, _ = make_package(tmp_path)
    task_path = root / "task.yaml"
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    task["id"] = "different_task"
    write_file(task_path, yaml.safe_dump(task))

    errors = validate_task_package(root)
    assert any("SHA-256 mismatch: task.yaml" in e for e in errors)
    assert any("task.yaml id does not match" in e for e in errors)


def test_missing_hidden_verifier_is_rejected(tmp_path):
    root, _ = make_package(tmp_path)
    (root / "hidden_tests" / "test_main.py").unlink()

    errors = validate_task_package(root)
    assert any("Missing or unsafe package path" in e for e in errors)


def test_manifest_must_be_a_json_object(tmp_path):
    root, _ = make_package(tmp_path)
    write_file(root / "manifest.json", "[]")

    errors = validate_task_package(root)
    assert any("Cannot load manifest.json: TypeError" in e for e in errors)


def test_unsafe_relative_paths_are_rejected():
    for path in ("../outside.py", "/absolute.py", "repo/../../outside.py"):
        try:
            safe_relative_path(path)
        except ValueError:
            continue
        raise AssertionError(f"Unsafe path was accepted: {path}")


def test_noncanonical_windows_path_is_rejected():
    try:
        safe_relative_path("repo\\main.py")
    except ValueError:
        return
    raise AssertionError("Windows-style path was accepted.")


def test_wrong_verifier_location_is_rejected(tmp_path):
    root, manifest = make_package(tmp_path)
    manifest["verifier"]["test_path"] = "../outside.py"
    write_file(root / "manifest.json", json.dumps(manifest))

    errors = validate_task_package(root)
    assert any("unsafe package path" in e.lower() for e in errors)
