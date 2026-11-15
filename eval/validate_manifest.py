"""Validate NOVA-EVAL task manifests and package integrity."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "eval" / "specs" / "task_manifest.schema.json"

GATES = (
    "V01_starter_rejection",
    "V02_reference_acceptance",
    "V03_incorrect_mutation_rejection",
    "V04_protected_file_integrity",
    "V05_hidden_test_isolation",
    "V06_repeatability",
    "V07_deterministic_scoring",
    "V08_budget_feasibility",
    "V09_no_verifier_leakage",
    "V10_provenance",
)

IGNORED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".venv",
}

IGNORED_SUFFIXES = {".pyc", ".pyo"}


def safe_relative_path(value: str) -> str:
    """Validate a portable package-relative POSIX path."""
    if not isinstance(value, str) or not value:
        raise ValueError("Path must be a non-empty string.")

    if "\\" in value or "\x00" in value or ":" in value:
        raise ValueError(f"Non-portable or unsafe path: {value!r}")

    path = PurePosixPath(value)

    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe relative path: {value!r}")

    if path.as_posix() != value:
        raise ValueError(f"Path is not canonical: {value!r}")

    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)

    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object.")

    return value


def discover_package_files(task_root: Path) -> tuple[set[str], list[str]]:
    """Find package files while rejecting symlinks and path escapes."""
    files: set[str] = set()
    errors: list[str] = []
    root = task_root.resolve()

    for current, directories, filenames in os.walk(task_root, followlinks=False):
        current_path = Path(current)

        retained_directories = []

        for name in directories:
            child = current_path / name

            if child.is_symlink():
                errors.append(f"Symlink directory is not permitted: {child}")
                continue

            if name in IGNORED_DIRS:
                continue

            retained_directories.append(name)

        directories[:] = retained_directories

        for name in filenames:
            path = current_path / name

            if path.is_symlink():
                errors.append(f"Symlink file is not permitted: {path}")
                continue

            if path.suffix.lower() in IGNORED_SUFFIXES:
                continue

            try:
                resolved = path.resolve(strict=True)
                relative = resolved.relative_to(root).as_posix()
            except (OSError, ValueError):
                errors.append(f"File escapes task package or cannot be resolved: {path}")
                continue

            files.add(relative)

    return files, errors


def validate_task_metadata(task_root: Path, manifest: dict) -> list[str]:
    errors: list[str] = []
    task_path = task_root / "task.yaml"

    try:
        with task_path.open("r", encoding="utf-8-sig") as handle:
            task = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        return [f"Cannot load task.yaml: {type(exc).__name__}"]

    if not isinstance(task, dict):
        return ["task.yaml must contain a YAML object."]

    required = (
        "id",
        "family",
        "description",
        "prompt",
        "language",
        "framework",
        "difficulty",
        "protected_paths",
        "success_criteria",
        "forbidden_actions",
        "task_timeout_seconds",
        "max_steps",
    )

    for field in required:
        if field not in task:
            errors.append(f"task.yaml is missing required field: {field}")

    if errors:
        return errors

    if task["id"] != manifest["task_id"]:
        errors.append("task.yaml id does not match manifest task_id.")

    if task["family"] != manifest["family"]:
        errors.append("task.yaml family does not match manifest family.")

    environment = manifest["environment"]

    for field in ("language", "framework"):
        if task[field] != environment[field]:
            errors.append(f"task.yaml {field} does not match manifest environment.")

    for field in ("description", "prompt", "difficulty", "language", "framework"):
        if not isinstance(task[field], str) or not task[field].strip():
            errors.append(f"task.yaml {field} must be a non-empty string.")

    for field in ("protected_paths", "success_criteria", "forbidden_actions"):
        value = task[field]

        if not isinstance(value, list):
            errors.append(f"task.yaml {field} must be a list.")
        elif any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"Every task.yaml {field} item must be a non-empty string.")

    for field in ("task_timeout_seconds", "max_steps"):
        value = task[field]

        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"task.yaml {field} must be a positive integer.")

    repo_root = task_root / "repo"

    if not repo_root.is_dir():
        errors.append("Task package is missing repo/.")

    for protected in task["protected_paths"]:
        if not isinstance(protected, str):
            continue

        try:
            relative = safe_relative_path(protected)
            target = (repo_root / relative).resolve(strict=True)
            target.relative_to(repo_root.resolve())

            if not target.is_file():
                errors.append(f"Protected path is not a file: {protected}")
        except (ValueError, OSError):
            errors.append(f"Invalid or missing protected path: {protected}")

    return errors


def validate_task_package(
    task_dir: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> list[str]:
    """Return all detectable manifest and package integrity errors."""
    errors: list[str] = []
    task_root = task_dir.resolve()

    if not task_root.is_dir():
        return [f"Task directory does not exist: {task_root}"]

    manifest_path = task_root / "manifest.json"

    try:
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return [f"Cannot load manifest.json: {type(exc).__name__}: {exc}"]

    try:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

        schema_errors = sorted(
            validator.iter_errors(manifest),
            key=lambda error: list(map(str, error.absolute_path)),
        )

        for error in schema_errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"Manifest schema error at {location}: {error.message}")

    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return [f"Cannot validate manifest schema: {type(exc).__name__}: {exc}"]

    if errors:
        return errors

    if manifest["task_id"] != task_root.name:
        errors.append(
            f"Manifest task_id {manifest['task_id']!r} "
            f"does not match directory name {task_root.name!r}."
        )

    required_paths = (
        "task.yaml",
        "VALIDITY.md",
        "repo",
        "reference",
        manifest["verifier"]["test_path"],
    )

    for raw_path in required_paths:
        try:
            relative = safe_relative_path(raw_path)
            target = (task_root / relative).resolve(strict=True)
            target.relative_to(task_root)

            if raw_path in {"repo", "reference"} and not target.is_dir():
                errors.append(f"Required directory is missing: {raw_path}")
            elif raw_path not in {"repo", "reference"} and not target.exists():
                errors.append(f"Required package path is missing: {raw_path}")

        except (ValueError, OSError):
            errors.append(f"Missing or unsafe package path: {raw_path}")

    if not (task_root / "hidden_tests").is_dir():
        errors.append("Task package is missing hidden_tests/.")

    if manifest["verifier"]["type"] == "pytest":
        test_path = PurePosixPath(manifest["verifier"]["test_path"])

        if not test_path.parts or test_path.parts[0] != "hidden_tests":
            errors.append("Pytest verifier test_path must be inside hidden_tests/.")

    errors.extend(validate_task_metadata(task_root, manifest))

    declared = manifest["files"]
    normalized_declared: dict[str, str] = {}
    casefolded: set[str] = set()

    for raw_path, expected_hash in declared.items():
        try:
            relative = safe_relative_path(raw_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        folded = relative.casefold()

        if folded in casefolded:
            errors.append(f"Case-insensitive duplicate manifest path: {relative}")
            continue

        casefolded.add(folded)
        normalized_declared[relative] = expected_hash

        target = task_root / relative

        if target.is_symlink() or not target.is_file():
            errors.append(f"Declared file is missing or is not a regular file: {relative}")
            continue

        try:
            target.resolve(strict=True).relative_to(task_root)
        except (OSError, ValueError):
            errors.append(f"Declared file escapes task package: {relative}")
            continue

        actual_hash = sha256_file(target)

        if actual_hash != expected_hash:
            errors.append(f"SHA-256 mismatch: {relative}")

    discovered, discovery_errors = discover_package_files(task_root)
    errors.extend(discovery_errors)

    discovered.discard("manifest.json")

    declared_set = set(normalized_declared)

    for missing in sorted(discovered - declared_set):
        errors.append(f"Untracked package file is missing from manifest: {missing}")

    for extra in sorted(declared_set - discovered):
        errors.append(f"Manifest references an undiscovered file: {extra}")

    if manifest["status"] == "ACCEPTED":
        gates = manifest["validation"]

        for gate in GATES:
            if gates[gate]["status"] != "pass":
                errors.append(f"Accepted task has a non-passing gate: {gate}")

            if not gates[gate]["evidence"].strip():
                errors.append(f"Accepted task has no evidence for gate: {gate}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a NOVA-EVAL task manifest and package."
    )
    parser.add_argument("task_dir", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
    )
    args = parser.parse_args()

    errors = validate_task_package(args.task_dir, args.schema)

    if errors:
        print(f"INVALID: {args.task_dir}")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"VALID: {args.task_dir}")
    print("Manifest schema and package integrity checks passed.")
    print("Note: validation gate evidence is checked for completeness, not independently executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
