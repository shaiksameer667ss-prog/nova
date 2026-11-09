import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def legacy_list_files(workspace: Path) -> list[str]:
    workspace_root = Path(workspace).resolve()
    return [
        str(path.relative_to(workspace))
        for path in workspace_root.rglob("*")
        if path.is_file()
    ]


def main() -> None:
    original_cwd = os.getcwd()
    result = None

    with TemporaryDirectory(prefix="nova-genesis3-") as temp:
        try:
            os.chdir(temp)

            workspace = Path("workspace")
            workspace.mkdir()
            (workspace / "marker.txt").write_text(
                "fixture\n", encoding="utf-8"
            )

            try:
                legacy_list_files(workspace)
            except ValueError as exc:
                result = {
                    "fixture": "legacy_list_files_relative_path",
                    "reproduced": True,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "expected_remediation": "TOOL_REPAIR",
                }
            else:
                raise AssertionError(
                    "Historical ValueError was not reproduced."
                )
        finally:
            # Restore CWD BEFORE TemporaryDirectory attempts cleanup.
            os.chdir(original_cwd)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
