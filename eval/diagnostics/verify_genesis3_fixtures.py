import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transient_failure import TransientListFiles
from persistent_failure import PersistentListFiles


EXPECTED = "alpha.txt\nbeta.txt\nnested/gamma.txt"


def prepare_workspace() -> Path:
    workspace = Path("workspace")
    workspace.mkdir()
    (workspace / "alpha.txt").write_text("alpha", encoding="utf-8")
    (workspace / "beta.txt").write_text("beta", encoding="utf-8")
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "gamma.txt").write_text("gamma", encoding="utf-8")
    return workspace


def main() -> None:
    original_cwd = os.getcwd()

    with TemporaryDirectory(prefix="nova-genesis3-fixtures-") as temp:
        try:
            os.chdir(temp)
            workspace = prepare_workspace()

            transient = TransientListFiles()
            transient_errors = []

            for _ in range(2):
                try:
                    transient(workspace)
                except ValueError as exc:
                    transient_errors.append(str(exc))
                else:
                    raise AssertionError("Transient fixture did not fail.")

            transient_success = transient(workspace)

            assert transient.calls == 3
            assert transient_errors[0] == transient_errors[1]
            assert "is not in the subpath of 'workspace'" in transient_errors[0]
            assert transient_success == EXPECTED

            persistent = PersistentListFiles()
            persistent_errors = []

            for _ in range(3):
                try:
                    persistent(workspace)
                except ValueError as exc:
                    persistent_errors.append(str(exc))
                else:
                    raise AssertionError("Persistent fixture did not fail.")

            assert persistent.calls == 3
            assert len(set(persistent_errors)) == 1
            assert all("is not in the subpath of 'workspace'" in message for message in persistent_errors)

            result = {
                "transient": {
                    "calls": transient.calls,
                    "first_two_failures_identical": True,
                    "third_call_succeeded": True,
                    "returned_files": transient_success.splitlines(),
                },
                "persistent": {
                    "calls": persistent.calls,
                    "all_three_failures_identical": True,
                    "exception_type": "ValueError",
                },
                "expected_files": EXPECTED.splitlines(),
                "model_calls": 0,
            }
        finally:
            os.chdir(original_cwd)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
