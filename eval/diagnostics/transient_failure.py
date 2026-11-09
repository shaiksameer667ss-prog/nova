from pathlib import Path


def legacy_failure(workspace: Path):
    """Reproduce the historical relative_to path-resolution defect."""
    workspace_root = Path(workspace).resolve()
    return [
        str(path.relative_to(workspace))
        for path in workspace_root.rglob("*")
        if path.is_file()
    ]


def fixed_list_files(workspace: Path) -> str:
    """Return a correctly resolved, sorted workspace listing."""
    workspace_root = Path(workspace).resolve()
    entries = sorted(
        path.relative_to(workspace_root)
        for path in workspace_root.rglob("*")
        if path.is_file()
    )
    return "\n".join(entry.as_posix() for entry in entries) if entries else "(empty)"


class TransientListFiles:
    """Fail on calls 1 and 2; succeed from call 3 onward."""

    def __init__(self):
        self.calls = 0

    def __call__(self, workspace: Path) -> str:
        self.calls += 1
        if self.calls <= 2:
            return legacy_failure(workspace)
        return fixed_list_files(workspace)
