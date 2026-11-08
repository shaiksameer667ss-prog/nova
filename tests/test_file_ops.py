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