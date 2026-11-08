import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_python(code: str, cwd: Path, timeout: float = 30.0) -> ExecResult:
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ExecResult(result.stdout, result.stderr, result.returncode, False)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return ExecResult(out, err, -1, True)