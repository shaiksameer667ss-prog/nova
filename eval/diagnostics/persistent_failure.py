from pathlib import Path

from transient_failure import legacy_failure


class PersistentListFiles:
    """Reproduce the same legacy ValueError on every call."""

    def __init__(self):
        self.calls = 0

    def __call__(self, workspace: Path):
        self.calls += 1
        return legacy_failure(workspace)
