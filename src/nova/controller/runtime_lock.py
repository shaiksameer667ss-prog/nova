import os
from pathlib import Path


class RuntimeLockError(RuntimeError):
    pass


class RuntimeLock:
    """Exclusive process-level lock for one NOVA runtime database."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._stream = None
        self._locked = False

    def acquire(self):
        if self._locked:
            raise RuntimeLockError("This lock is already acquired.")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")

        try:
            # Windows byte-range locking requires a byte to exist.
            self._stream.seek(0, os.SEEK_END)
            if self._stream.tell() == 0:
                self._stream.write(b"\0")
                self._stream.flush()

            self._stream.seek(0)

            if os.name == "nt":
                import msvcrt
                msvcrt.locking(
                    self._stream.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
            else:
                import fcntl
                fcntl.flock(
                    self._stream.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )

            self._locked = True
            return self

        except (OSError, BlockingIOError) as exc:
            self._stream.close()
            self._stream = None
            raise RuntimeLockError(
                f"Another NOVA process holds runtime lock: {self.path}"
            ) from exc

    def release(self):
        if not self._locked or self._stream is None:
            return

        try:
            self._stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(
                    self._stream.fileno(),
                    msvcrt.LK_UNLCK,
                    1,
                )
            else:
                import fcntl
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._locked = False
            self._stream.close()
            self._stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False
