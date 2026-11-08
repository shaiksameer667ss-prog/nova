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
    target = _safe_path(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


def read_file(workspace: Path, path: str) -> str:
    target = _safe_path(workspace, path)
    if not target.exists():
        raise FileNotFoundError(f"not found: {path}")
    return target.read_text(encoding="utf-8")


def list_files(workspace: Path, subdir: str = ".") -> str:
    root = _safe_path(workspace, subdir)
    if not root.exists():
        return "(empty)"
    entries = sorted(p.relative_to(workspace) for p in root.rglob("*") if p.is_file())
    if not entries:
        return "(empty)"
    return "\n".join(str(e) for e in entries)