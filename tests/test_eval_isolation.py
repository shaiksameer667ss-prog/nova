"""Security boundary tests for the current NOVA-EVAL harness.

The verifier subprocess test is a controlled vulnerability demonstration,
not an assertion that the harness is safely sandboxed.
"""

import hashlib

import pytest

from eval.harness.runner import _run_hidden_tests
from nova.controller.loop import _dispatch
from nova.tools.file_ops import WorkspaceError, list_files, read_file, write_file


def test_file_tools_reject_workspace_path_traversal(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    secret = tmp_path / "secret.txt"
    secret.write_text("temporary sentinel", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        read_file(workspace, "../secret.txt")

    with pytest.raises(WorkspaceError):
        write_file(workspace, "../modified.txt", "not allowed")

    with pytest.raises(WorkspaceError):
        list_files(workspace, "..")

    assert secret.read_text(encoding="utf-8") == "temporary sentinel"
    assert not (tmp_path / "modified.txt").exists()


def test_controller_does_not_dispatch_arbitrary_execution(tmp_path):
    for action in ("exec", "run_python", "shell"):
        with pytest.raises(ValueError, match="unknown action"):
            _dispatch({"action": action, "code": "print('no')"}, None)


def test_verifier_subprocess_can_read_test_source_and_host_sentinel(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "agent_workspace"
    hidden_tests = tmp_path / "hidden_tests"
    workspace.mkdir()
    hidden_tests.mkdir()

    sentinel = tmp_path / "host_sentinel.txt"
    sentinel.write_text("NOVA_EVAL_TEMP_SENTINEL", encoding="utf-8")
    monkeypatch.setenv("NOVA_EVAL_SENTINEL", str(sentinel))

    # This agent-controlled module executes when imported by pytest.
    # It reads the verifier test source and a file outside the workspace.
    probe = '''import os
from pathlib import Path

test_source = Path.cwd() / "test_probe.py"
OBSERVED_TEST_SOURCE = test_source.read_text(encoding="utf-8")

sentinel = Path(os.environ["NOVA_EVAL_SENTINEL"])
OBSERVED_SENTINEL = sentinel.read_text(encoding="utf-8")

sentinel.write_text("MODIFIED_BY_AGENT_CODE", encoding="utf-8")
'''

    (workspace / "probe.py").write_text(probe, encoding="utf-8")

    test_source = '''from probe import OBSERVED_SENTINEL, OBSERVED_TEST_SOURCE


def test_agent_code_can_observe_verifier_and_host_file():
    assert "NOVA_HIDDEN_TEST_MARKER" in OBSERVED_TEST_SOURCE
    assert OBSERVED_SENTINEL == "NOVA_EVAL_TEMP_SENTINEL"
'''

    test_source = test_source.replace(
        "test_probe.py",
        "NOVA_HIDDEN_TEST_MARKER",
    )

    test_path = hidden_tests / "test_probe.py"
    test_path.write_text(test_source, encoding="utf-8")

    original_test_hash = hashlib.sha256(test_path.read_bytes()).hexdigest()

    passed, output = _run_hidden_tests(workspace, hidden_tests)

    assert passed, output
    assert sentinel.read_text(encoding="utf-8") == "MODIFIED_BY_AGENT_CODE"

    # The original hidden-test file was copied for verification, not modified.
    assert hashlib.sha256(test_path.read_bytes()).hexdigest() == original_test_hash

    assert not (workspace / "test_probe.py").exists()


def test_candidate_workspace_has_no_reference_or_hidden_test_files(tmp_path):
    task_root = tmp_path / "task"
    workspace = tmp_path / "workspace"

    (task_root / "repo").mkdir(parents=True)
    (task_root / "reference").mkdir()
    (task_root / "hidden_tests").mkdir()
    workspace.mkdir()

    (task_root / "repo" / "main.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (task_root / "reference" / "main.py").write_text(
        "VALUE = 2\n",
        encoding="utf-8",
    )
    (task_root / "hidden_tests" / "test_main.py").write_text(
        "SECRET = 'hidden'\n",
        encoding="utf-8",
    )

    import shutil

    for source in (task_root / "repo").iterdir():
        if source.is_file():
            shutil.copy2(source, workspace / source.name)

    visible = {path.name for path in workspace.iterdir()}

    assert visible == {"main.py"}
    assert not (workspace / "reference").exists()
    assert not (workspace / "hidden_tests").exists()
