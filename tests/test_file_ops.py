from pathlib import Path

import pytest

from nova.tools.file_ops import (
    WorkspaceError,
    list_files,
    read_file,
    write_file,
)


def test_write_then_read(tmp_path):
    assert "wrote" in write_file(tmp_path, "a.txt", "hello")
    assert read_file(tmp_path, "a.txt") == "hello"


def test_write_creates_nested_dirs(tmp_path):
    write_file(tmp_path, "sub/dir/b.txt", "x")
    assert (tmp_path / "sub" / "dir" / "b.txt").exists()


def test_read_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_file(tmp_path, "nope.txt")


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(WorkspaceError):
        write_file(tmp_path, "../evil.txt", "x")


def test_list_files_empty(tmp_path):
    assert list_files(tmp_path) == "(empty)"


def test_list_files_after_write(tmp_path):
    write_file(tmp_path, "a.txt", "1")
    write_file(tmp_path, "sub/b.txt", "2")
    listing = list_files(tmp_path)
    assert "a.txt" in listing
    assert "sub\\b.txt" in listing or "sub/b.txt" in listing


def test_list_files_relative_path(tmp_path):
    """Regression test: Ensure list_files works when workspace is relative."""
    # Change CWD to tmp_path so we can test a relative path
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        rel_workspace = Path("workspace")
        rel_workspace.mkdir()
        write_file(rel_workspace, "test.py", "print()")
        
        # This previously raised: ValueError: ... is not in the subpath of 'workspace'
        result = list_files(rel_workspace)
        assert "test.py" in result
    finally:
        os.chdir(old_cwd)
def test_identical_write_does_not_replace_file(tmp_path, monkeypatch):
    from nova.tools import file_ops

    write_file(tmp_path, "a.txt", "original")
    target = tmp_path / "a.txt"
    original_mtime = target.stat().st_mtime_ns

    def unexpected_replace(*args, **kwargs):
        raise AssertionError("Identical writes must not replace the file.")

    monkeypatch.setattr(file_ops.os, "replace", unexpected_replace)

    result = write_file(tmp_path, "a.txt", "original")

    assert result.startswith("unchanged")
    assert target.read_text(encoding="utf-8") == "original"
    assert target.stat().st_mtime_ns == original_mtime


def test_different_content_replaces_existing_file(tmp_path):
    write_file(tmp_path, "a.txt", "old")
    result = write_file(tmp_path, "a.txt", "new")

    assert result.startswith("wrote")
    assert read_file(tmp_path, "a.txt") == "new"


def test_atomic_replace_uses_destination_directory(tmp_path, monkeypatch):
    from nova.tools import file_ops

    original_replace = file_ops.os.replace
    observed = {}

    def checked_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)

        observed["source_parent"] = source_path.parent.resolve()
        observed["destination_parent"] = destination_path.parent.resolve()

        return original_replace(source, destination)

    monkeypatch.setattr(file_ops.os, "replace", checked_replace)

    write_file(tmp_path, "sub/a.txt", "content")

    assert observed["source_parent"] == observed["destination_parent"]
    assert read_file(tmp_path, "sub/a.txt") == "content"


def test_failed_replace_preserves_original_and_cleans_temp(
    tmp_path, monkeypatch
):
    from nova.tools import file_ops

    write_file(tmp_path, "a.txt", "original")

    def failed_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(file_ops.os, "replace", failed_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        write_file(tmp_path, "a.txt", "replacement")

    assert read_file(tmp_path, "a.txt") == "original"
    assert list(tmp_path.glob(".a.txt.*.nova-tmp")) == []


def test_empty_file_can_be_written_atomically(tmp_path):
    result = write_file(tmp_path, "empty.txt", "")

    assert result.startswith("wrote")
    assert read_file(tmp_path, "empty.txt") == ""


def test_non_string_content_is_rejected(tmp_path):
    with pytest.raises(TypeError, match="content must be a string"):
        write_file(tmp_path, "a.txt", 123)
