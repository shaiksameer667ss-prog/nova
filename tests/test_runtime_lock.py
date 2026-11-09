import subprocess
import sys

import pytest

from nova.controller.runtime_lock import RuntimeLock, RuntimeLockError


def test_lock_creates_parent_directory_and_releases(tmp_path):
    lock_path = tmp_path / "nested" / "nova.runtime.lock"

    with RuntimeLock(lock_path):
        assert lock_path.exists()

    # Reacquisition after release must succeed.
    with RuntimeLock(lock_path):
        assert lock_path.exists()


def test_second_process_cannot_acquire_held_lock(tmp_path):
    lock_path = tmp_path / "nova.runtime.lock"

    child_code = """
import sys
from pathlib import Path
from nova.controller.runtime_lock import RuntimeLock, RuntimeLockError

try:
    with RuntimeLock(Path(sys.argv[1])):
        print("ACQUIRED")
except RuntimeLockError:
    print("BLOCKED")
"""

    with RuntimeLock(lock_path):
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(lock_path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED"


def test_lock_can_be_acquired_after_owner_exits(tmp_path):
    lock_path = tmp_path / "nova.runtime.lock"

    with RuntimeLock(lock_path):
        pass

    with RuntimeLock(lock_path):
        assert lock_path.exists()


def test_repeated_release_is_safe(tmp_path):
    lock = RuntimeLock(tmp_path / "nova.runtime.lock")
    lock.acquire()
    lock.release()
    lock.release()


def test_double_acquire_on_same_instance_is_rejected(tmp_path):
    lock = RuntimeLock(tmp_path / "nova.runtime.lock")
    lock.acquire()

    try:
        with pytest.raises(RuntimeLockError, match="already acquired"):
            lock.acquire()
    finally:
        lock.release()
