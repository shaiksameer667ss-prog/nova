import os
import tempfile
from pathlib import Path


class WorkspaceError(ValueError):
    pass


def _safe_path(workspace: Path, rel: str) -> Path:
    root = Path(workspace).resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise WorkspaceError(f"path escapes workspace: {rel}") from None
    return target


def write_file(workspace: Path, path: str, content: str) -> str:
    """Write atomically and avoid rewriting identical file contents."""
    if not isinstance(content, str):
        raise TypeError("content must be a string.")

    target = _safe_path(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode("utf-8")

    # Idempotency: identical content requires no filesystem mutation.
    if target.is_file() and target.read_bytes() == content_bytes:
        return f"unchanged {len(content)} chars at {path}"

    # Create the temporary file in the destination directory so os.replace
    # stays on the same filesystem.
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".nova-tmp",
        dir=str(target.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(content_bytes)
            stream.flush()
            os.fsync(stream.fileno())

        # Readers see either the old file or the complete new file.
        os.replace(temp_path, target)

    except BaseException:
        if fd != -1:
            os.close(fd)

        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

        raise

    return f"wrote {len(content)} chars to {path}"


def read_file(workspace: Path, path: str) -> str:
    target = _safe_path(workspace, path)
    if not target.exists():
        raise FileNotFoundError(f"not found: {path}")
    return target.read_text(encoding="utf-8")


def list_files(workspace: Path, subdir: str = ".") -> str:
    workspace_root = Path(workspace).resolve()
    root = _safe_path(workspace_root, subdir)
    if not root.exists():
        return "(empty)"
    
    # Both paths are absolute now, so relative_to works correctly.
    entries = sorted(
        p.relative_to(workspace_root)
        for p in root.rglob("*")
        if p.is_file()
    )
    if not entries:
        return "(empty)"
    return "\n".join(str(entry) for entry in entries)