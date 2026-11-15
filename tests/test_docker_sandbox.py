import json
import os
import subprocess

import pytest

from eval.harness.docker_sandbox import (
    PINNED_PYTHON_IMAGE,
    DockerSandboxRunner,
    SandboxError,
    SandboxLimits,
)


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()
    return DockerSandboxRunner(root)


@pytest.fixture
def workspace(sandbox):
    path = sandbox.workspace_root / "task-001"
    path.mkdir()
    (path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    return path


def completed(args, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args, returncode, stdout, stderr
    )


def test_default_image_is_immutable_digest():
    assert PINNED_PYTHON_IMAGE.startswith("python@sha256:")
    assert len(PINNED_PYTHON_IMAGE.rsplit(":", 1)[1]) == 64


def test_rejects_mutable_image_tag(tmp_path):
    with pytest.raises(ValueError, match="immutable sha256"):
        DockerSandboxRunner(tmp_path / "workspaces", image="python:3.12-slim")


def test_rejects_invalid_resource_limits():
    with pytest.raises(ValueError, match="memory_mb"):
        SandboxLimits(memory_mb=0)

    with pytest.raises(ValueError, match="cpu_count"):
        SandboxLimits(cpu_count=float("inf"))

    with pytest.raises(ValueError, match="pids_limit"):
        SandboxLimits(pids_limit=-1)


def test_accepts_workspace_inside_configured_root(sandbox, workspace):
    assert sandbox._validate_workspace(workspace) == workspace.resolve()


def test_rejects_workspace_outside_root(sandbox, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(SandboxError, match="inside"):
        sandbox._validate_workspace(outside)


def test_rejects_workspace_root_itself(sandbox):
    with pytest.raises(SandboxError, match="entire workspace root"):
        sandbox._validate_workspace(sandbox.workspace_root)


def test_rejects_symlink_workspace(sandbox, workspace):
    alias = sandbox.workspace_root / "alias"
    alias.symlink_to(workspace, target_is_directory=True)

    with pytest.raises(SandboxError, match="Symbolic links"):
        sandbox._validate_workspace(alias)


def test_rejects_nested_symlink(sandbox, workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of workspace", encoding="utf-8")
    (workspace / "linked.txt").symlink_to(outside)

    with pytest.raises(SandboxError, match="Symbolic links"):
        sandbox._validate_workspace(workspace)


@pytest.mark.parametrize(
    "forbidden",
    [".git", ".env", ".venv", "hidden_tests", "reference", "verifier"],
)
def test_rejects_forbidden_nested_paths(sandbox, workspace, forbidden):
    nested = workspace / "subdir" / forbidden
    nested.mkdir(parents=True)

    with pytest.raises(SandboxError, match="forbidden"):
        sandbox._validate_workspace(workspace)


def test_rejects_hard_linked_workspace_files(sandbox, workspace, tmp_path):
    original = workspace / "main.py"
    linked = workspace / "linked.py"
    os.link(original, linked)

    with pytest.raises(SandboxError, match="Hard-linked"):
        sandbox._validate_workspace(workspace)


def test_rejects_command_with_null_byte(sandbox):
    with pytest.raises(ValueError, match="valid string"):
        sandbox._validate_command(["python", "bad\x00argument"])


def test_rejects_empty_command(sandbox):
    with pytest.raises(ValueError, match="non-empty"):
        sandbox._validate_command([])


def test_docker_environment_removes_external_connection_overrides(
    sandbox, monkeypatch
):
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        monkeypatch.setenv(key, "unexpected-value")

    env = sandbox._docker_env()

    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        assert key not in env


def test_requires_rootless_daemon_and_seccomp(sandbox, monkeypatch):
    options = json.dumps(["name=seccomp,profile=builtin", "name=rootless"])

    monkeypatch.setattr(
        sandbox,
        "_docker",
        lambda args: completed(args, stdout=options),
    )
    sandbox._require_rootless_daemon()


def test_rejects_non_rootless_daemon(sandbox, monkeypatch):
    options = json.dumps(["name=seccomp,profile=builtin"])

    monkeypatch.setattr(
        sandbox,
        "_docker",
        lambda args: completed(args, stdout=options),
    )

    with pytest.raises(SandboxError, match="not running in rootless"):
        sandbox._require_rootless_daemon()


def test_rejects_daemon_without_seccomp(sandbox, monkeypatch):
    options = json.dumps(["name=rootless"])

    monkeypatch.setattr(
        sandbox,
        "_docker",
        lambda args: completed(args, stdout=options),
    )

    with pytest.raises(SandboxError, match="seccomp"):
        sandbox._require_rootless_daemon()


def test_run_builds_restricted_container_and_cleans_it_up(
    sandbox, workspace, monkeypatch
):
    calls = []

    def fake_docker(args, **kwargs):
        calls.append(list(args))
        if args[0] == "create":
            return completed(args, stdout="a" * 64 + "\n")
        if args[:2] == ["rm", "--force"]:
            return completed(args)
        raise AssertionError(f"Unexpected Docker command: {args}")

    monkeypatch.setattr(sandbox, "_require_rootless_daemon", lambda: None)
    monkeypatch.setattr(sandbox, "_docker", fake_docker)
    monkeypatch.setattr(
        sandbox,
        "_attached_execution",
        lambda container_id, command_input, timeout_seconds: (
            0, "candidate finished\n", "", False, False, 0.1
        ),
    )

    result = sandbox.run(
        workspace,
        ["python", "-B", "-c", "print('candidate finished')"],
        stdin="input",
    )

    assert result.succeeded
    assert result.exit_code == 0
    assert result.stdout == "candidate finished\n"
    assert result.container_id == "a" * 64

    create_args = calls[0]
    assert create_args[0] == "create"
    assert "--pull=never" in create_args
    assert "--network=none" in create_args
    assert "--read-only" in create_args
    assert "--user" in create_args
    assert create_args[create_args.index("--user") + 1] == "65532:65532"
    assert "--cap-drop=ALL" in create_args
    assert "--security-opt=no-new-privileges:true" in create_args
    assert "--memory-swap" in create_args
    assert "--pids-limit" in create_args
    assert "--env=PYTHONDONTWRITEBYTECODE=1" in create_args

    mount = create_args[create_args.index("--mount") + 1]
    assert mount == f"type=bind,src={workspace.resolve()},dst=/workspace,readonly"

    assert calls[-1][:2] == ["rm", "--force"]


def test_input_limit_rejected_before_docker(sandbox, workspace, monkeypatch):
    monkeypatch.setattr(
        sandbox,
        "_require_rootless_daemon",
        lambda: pytest.fail("Docker must not be called"),
    )

    with pytest.raises(ValueError, match="input limit"):
        sandbox.run(workspace, ["python", "-c", "pass"], stdin="x" * 70000)


def test_failed_execution_still_removes_container(
    sandbox, workspace, monkeypatch
):
    calls = []

    def fake_docker(args, **kwargs):
        calls.append(list(args))
        if args[0] == "create":
            return completed(args, stdout="b" * 64 + "\n")
        if args[:2] == ["rm", "--force"]:
            return completed(args)
        raise AssertionError(f"Unexpected Docker command: {args}")

    monkeypatch.setattr(sandbox, "_require_rootless_daemon", lambda: None)
    monkeypatch.setattr(sandbox, "_docker", fake_docker)

    def fail_execution(*args, **kwargs):
        raise RuntimeError("simulated execution failure")

    monkeypatch.setattr(sandbox, "_attached_execution", fail_execution)

    with pytest.raises(RuntimeError, match="simulated"):
        sandbox.run(workspace, ["python", "-c", "pass"])

    assert calls[-1][:2] == ["rm", "--force"]


def test_invalid_create_response_triggers_cleanup(
    sandbox, workspace, monkeypatch
):
    calls = []

    def fake_docker(args, **kwargs):
        calls.append(list(args))
        if args[0] == "create":
            return completed(args, stdout="not-a-container-id\n")
        if args[:2] == ["rm", "--force"]:
            return completed(args)
        raise AssertionError(f"Unexpected Docker command: {args}")

    monkeypatch.setattr(sandbox, "_require_rootless_daemon", lambda: None)
    monkeypatch.setattr(sandbox, "_docker", fake_docker)

    with pytest.raises(SandboxError, match="invalid container ID"):
        sandbox.run(workspace, ["python", "-B", "-c", "pass"])

    assert calls[-1][:2] == ["rm", "--force"]
    assert calls[-1][2].startswith("nova-eval-")


def test_create_timeout_triggers_best_effort_cleanup(
    sandbox, workspace, monkeypatch
):
    calls = []

    def fake_docker(args, **kwargs):
        calls.append(list(args))
        if args[0] == "create":
            raise SandboxError("Docker CLI command timed out")
        if args[:2] == ["rm", "--force"]:
            return completed(args)
        raise AssertionError(f"Unexpected Docker command: {args}")

    monkeypatch.setattr(sandbox, "_require_rootless_daemon", lambda: None)
    monkeypatch.setattr(sandbox, "_docker", fake_docker)

    with pytest.raises(SandboxError, match="timed out"):
        sandbox.run(workspace, ["python", "-B", "-c", "pass"])

    assert calls[-1][:2] == ["rm", "--force"]
    assert calls[-1][2].startswith("nova-eval-")
