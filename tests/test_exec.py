from pathlib import Path

from nova.tools.exec import run_python
from nova.tools.registry import Tool, ToolRegistry


def test_runs_simple_code(tmp_path):
    result = run_python('print("hi")', cwd=tmp_path, timeout=10)
    assert result.ok
    assert result.stdout.strip() == "hi"
    assert result.exit_code == 0
    assert result.timed_out is False


def test_captures_stderr_and_exit_code(tmp_path):
    result = run_python(
        'import sys; sys.stderr.write("bad"); sys.exit(3)',
        cwd=tmp_path,
        timeout=10,
    )
    assert result.exit_code == 3
    assert "bad" in result.stderr
    assert result.ok is False


def test_timeout_is_reported(tmp_path):
    result = run_python("import time; time.sleep(5)", cwd=tmp_path, timeout=1)
    assert result.timed_out is True
    assert result.ok is False


def test_creates_cwd_if_missing(tmp_path):
    target = tmp_path / "sub" / "dir"
    assert not target.exists()
    result = run_python('print("ok")', cwd=target, timeout=10)
    assert target.exists()
    assert result.ok


def test_registry_register_and_get():
    reg = ToolRegistry()
    t = Tool(name="echo", description="echo back", fn=lambda x: x)
    reg.register(t)
    assert reg.get("echo") is t
    assert len(reg) == 1
    assert reg.get("missing") is None


def test_registry_rejects_duplicate():
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="", fn=lambda: None))
    try:
        reg.register(Tool(name="t", description="", fn=lambda: None))
    except ValueError:
        return
    raise AssertionError("expected ValueError on duplicate registration")