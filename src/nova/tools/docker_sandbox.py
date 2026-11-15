"""Restricted, rootless Docker execution for NOVA-EVAL candidate workspaces.

This module executes untrusted task code. It does not run hidden tests.
The trusted verifier must remain outside the candidate container.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PINNED_PYTHON_IMAGE = (
    "python@sha256:"
    "5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"
)

_IMAGE_REF = re.compile(r"^[A-Za-z0-9._/:+-]+@sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")


class SandboxError(RuntimeError):
    """Raised when sandbox configuration or Docker execution fails."""


@dataclass(frozen=True)
class SandboxLimits:
    memory_mb: int = 256
    cpu_count: float = 0.5
    pids_limit: int = 64
    tmpfs_mb: int = 16
    timeout_seconds: float = 30.0
    max_input_bytes: int = 65536
    max_output_bytes: int = 524288
    docker_command_timeout: float = 10.0

    def __post_init__(self) -> None:
        for name in ("memory_mb", "pids_limit", "tmpfs_mb",
                     "max_input_bytes", "max_output_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        for name in ("cpu_count", "timeout_seconds", "docker_command_timeout"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")


@dataclass(frozen=True)
class SandboxResult:
    container_id: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.output_limited
        )


class DockerSandboxRunner:
    """Run one command in a disposable rootless Docker container."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        *,
        image: str = PINNED_PYTHON_IMAGE,
        docker_executable: str = "docker",
        limits: SandboxLimits | None = None,
    ) -> None:
        if not _IMAGE_REF.fullmatch(image):
            raise ValueError("image must be pinned to an immutable sha256 digest")

        self.image = image
        self.docker_executable = docker_executable
        self.limits = limits or SandboxLimits()

        if workspace_root is None:
            workspace_root = Path.home() / "nova-eval-lab" / "workspaces"

        root = Path(workspace_root).expanduser()

        # Do not allow WSL Windows-drive mounts to become the workspace root.
        if os.name == "posix" and root.absolute().as_posix().startswith("/mnt/"):
            raise SandboxError(
                "Workspace root must use the Linux filesystem, not a /mnt drive"
            )

        root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = root.resolve(strict=True)

    def _docker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # Force use of the explicitly selected rootless context.
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            env.pop(key, None)
        return env

    def _docker(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self.docker_executable,
            "--context",
            "rootless",
            *args,
        ]

        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.limits.docker_command_timeout,
                check=False,
                env=self._docker_env(),
            )
        except FileNotFoundError as exc:
            raise SandboxError("Docker CLI was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxError("Docker CLI command timed out") from exc

    def _require_rootless_daemon(self) -> None:
        result = self._docker(
            ["info", "--format", "{{json .SecurityOptions}}"]
        )
        if result.returncode != 0:
            raise SandboxError(
                f"Cannot query rootless Docker daemon: {result.stderr.strip()}"
            )

        try:
            options = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SandboxError("Docker returned invalid security information") from exc

        if not isinstance(options, list):
            raise SandboxError("Docker security options were not a list")

        if not any(item == "name=rootless" for item in options):
            raise SandboxError(
                "Selected Docker context is not running in rootless mode"
            )

        if not any(str(item).startswith("name=seccomp") for item in options):
            raise SandboxError("Docker seccomp filtering is not enabled")

    def _remove_container(self, container_name: str) -> None:
        removed = self._docker(
            ["rm", "--force", container_name],
            timeout=self.limits.docker_command_timeout,
        )
        if removed.returncode != 0:
            raise SandboxError(
                "Container cleanup failed; inspect Docker for leftover "
                f"container {container_name}: {removed.stderr.strip()}"
            )

    def _best_effort_remove_container(self, container_name: str) -> None:
        try:
            self._remove_container(container_name)
        except SandboxError:
            # Preserve the original creation error. The unique name is
            # reported by Docker if manual cleanup becomes necessary.
            pass

    def _validate_workspace(self, workspace: Path | str) -> Path:
        raw_path = Path(workspace).expanduser()
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path

        # Normalize "." and ".." without following symlinks, then inspect every
        # path component so an intermediate symlink cannot redirect the mount.
        lexical_path = Path(os.path.abspath(raw_path))
        try:
            relative = lexical_path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise SandboxError(
                "Workspace must be inside the configured workspace root"
            ) from exc

        if not relative.parts:
            raise SandboxError("Mounting the entire workspace root is forbidden")

        cursor = self.workspace_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise SandboxError(
                    f"Symbolic links are forbidden in workspace paths: {cursor}"
                )

        try:
            resolved_path = lexical_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise SandboxError("Workspace does not exist") from exc

        if resolved_path != lexical_path or not resolved_path.is_dir():
            raise SandboxError("Workspace must be a real directory without symlinks")

        if "," in str(resolved_path):
            raise SandboxError("Workspace paths containing commas are not supported")

        forbidden = {
            ".git", ".env", ".venv", "hidden_tests", "reference", "verifier"
        }
        if forbidden.intersection(relative.parts):
            raise SandboxError("Workspace path contains a forbidden component")

        root_device = resolved_path.stat().st_dev
        for item in resolved_path.rglob("*"):
            relative_parts = item.relative_to(resolved_path).parts
            if forbidden.intersection(relative_parts):
                raise SandboxError(
                    f"Workspace contains a forbidden path component: {item}"
                )
            if item.is_symlink():
                raise SandboxError(f"Symbolic links are forbidden in workspaces: {item}")
            if not item.is_file() and not item.is_dir():
                raise SandboxError(f"Special filesystem entries are forbidden: {item}")

            details = item.stat()
            if details.st_dev != root_device:
                raise SandboxError(f"Nested mount points are forbidden: {item}")
            if item.is_file() and details.st_nlink > 1:
                raise SandboxError(f"Hard-linked files are forbidden: {item}")

        return resolved_path

    @staticmethod
    def _validate_command(command: Sequence[str]) -> list[str]:
        if isinstance(command, (str, bytes)) or not command:
            raise ValueError("command must be a non-empty sequence of arguments")

        result = list(command)
        if any(not isinstance(arg, str) or "\x00" in arg for arg in result):
            raise ValueError("Every command argument must be a valid string")
        return result

    def _attached_execution(
        self,
        container_id: str,
        command_input: bytes,
        timeout_seconds: float,
    ) -> tuple[int, str, str, bool, bool, float]:
        start_time = time.monotonic()

        try:
            process = subprocess.Popen(
                [
                    self.docker_executable,
                    "--context",
                    "rootless",
                    "start",
                    "--attach",
                    "--interactive",
                    container_id,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._docker_env(),
            )
        except OSError as exc:
            raise SandboxError(f"Could not start container: {exc}") from exc

        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        total_output = [0]
        output_lock = threading.Lock()
        output_exceeded = threading.Event()

        def drain(stream, destination: bytearray) -> None:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return

                with output_lock:
                    remaining = self.limits.max_output_bytes - total_output[0]
                    allowed = max(0, min(len(chunk), remaining))
                    if allowed:
                        destination.extend(chunk[:allowed])
                        total_output[0] += allowed
                    exceeded = len(chunk) > allowed

                if exceeded:
                    output_exceeded.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return

        def feed_input() -> None:
            try:
                if command_input:
                    process.stdin.write(command_input)
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        stdout_thread = threading.Thread(
            target=drain, args=(process.stdout, stdout_buffer), daemon=True
        )
        stderr_thread = threading.Thread(
            target=drain, args=(process.stderr, stderr_buffer), daemon=True
        )
        input_thread = threading.Thread(target=feed_input, daemon=True)

        stdout_thread.start()
        stderr_thread.start()
        input_thread.start()

        timed_out = False
        deadline = start_time + timeout_seconds

        while process.poll() is None:
            if output_exceeded.is_set():
                break
            if time.monotonic() >= deadline:
                timed_out = True
                try:
                    process.kill()
                except OSError:
                    pass
                break
            time.sleep(0.01)

        try:
            exit_code = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait()

        input_thread.join(timeout=2)
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        duration = time.monotonic() - start_time
        return (
            exit_code,
            stdout_buffer.decode("utf-8", errors="replace"),
            stderr_buffer.decode("utf-8", errors="replace"),
            timed_out,
            output_exceeded.is_set(),
            duration,
        )

    def run(
        self,
        workspace: Path | str,
        command: Sequence[str],
        *,
        stdin: str | bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> SandboxResult:
        """Execute a command with no network, host environment or extra mounts.

        The workspace is the only host directory mounted, at /workspace.
        The caller is responsible for staging candidate files only.
        """
        workspace_path = self._validate_workspace(workspace)
        command_args = self._validate_command(command)

        if stdin is None:
            input_bytes = b""
        elif isinstance(stdin, str):
            input_bytes = stdin.encode("utf-8")
        elif isinstance(stdin, bytes):
            input_bytes = stdin
        else:
            raise TypeError("stdin must be str, bytes, or None")

        if len(input_bytes) > self.limits.max_input_bytes:
            raise ValueError("stdin exceeds the configured input limit")

        timeout = (
            self.limits.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")

        self._require_rootless_daemon()

        run_id = uuid.uuid4().hex
        container_name = f"nova-eval-{run_id}"
        create_args = [
            "create",
            "--pull=never",
            "--interactive",
            "--name",
            container_name,
            "--label",
            "org.nova-eval.managed=true",
            "--label",
            f"org.nova-eval.run={run_id}",
            "--network=none",
            "--read-only",
            "--user",
            "65532:65532",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory",
            f"{self.limits.memory_mb}m",
            "--memory-swap",
            f"{self.limits.memory_mb}m",
            "--cpus",
            format(self.limits.cpu_count, "g"),
            "--pids-limit",
            str(self.limits.pids_limit),
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self.limits.tmpfs_mb}m",
            "--shm-size=8m",
            "--ulimit",
            "nofile=128:128",
            "--ulimit",
            "core=0:0",
            "--mount",
            f"type=bind,src={workspace_path},dst=/workspace,readonly",
            "--workdir=/workspace",
            self.image,
            *command_args,
        ]

        try:
            created = self._docker(create_args)
        except SandboxError:
            # The CLI may time out after the daemon has already created it.
            self._best_effort_remove_container(container_name)
            raise

        if created.returncode != 0:
            self._best_effort_remove_container(container_name)
            raise SandboxError(
                f"Could not create sandbox container: {created.stderr.strip()}"
            )

        container_id = created.stdout.strip()
        if not _CONTAINER_ID.fullmatch(container_id):
            self._best_effort_remove_container(container_name)
            raise SandboxError(
                "Docker returned an invalid container ID; cleanup was attempted"
            )

        try:
            (
                exit_code,
                stdout,
                stderr,
                timed_out,
                output_limited,
                duration,
            ) = self._attached_execution(
                container_name, input_bytes, float(timeout)
            )
        finally:
            self._remove_container(container_name)

        return SandboxResult(
            container_id=container_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_limited=output_limited,
            duration_seconds=round(duration, 3),
        )
