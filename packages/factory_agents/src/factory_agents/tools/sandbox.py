"""Fail-closed execution of didactic Python snippets.

Production uses Bubblewrap to create a minimal Linux mount namespace with no
network. Outside that environment execution is disabled by default. The
``local-unsafe`` mode exists only for explicit development use and is never a
fallback for failed isolation.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

TIMEOUT_SECONDS = 15
MAX_OUTPUT_CHARS = 4000
MAX_CAPTURE_BYTES = 8192
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
FILE_LIMIT_BYTES = 1024 * 1024
WORKSPACE_LIMIT_BYTES = 16 * 1024 * 1024
CPU_SECONDS = 10
PROCESS_LIMIT = 64
FILE_DESCRIPTOR_LIMIT = 32
POLICY_EXIT_CODE = 77
POLICY_MARKER = "__SANDBOX_POLICY_VIOLATION__:"

logger = logging.getLogger(__name__)

if os.name != "nt":
    import resource


class SandboxMode(StrEnum):
    ISOLATED = "isolated"
    DISABLED = "disabled"
    LOCAL_UNSAFE = "local-unsafe"


class SandboxStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"
    POLICY_VIOLATION = "policy_violation"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SandboxResult:
    status: SandboxStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    canceled: bool = False
    policy_violation: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = 0

    def render_for_agent(self) -> str:
        if self.status == SandboxStatus.DISABLED:
            return (
                "(no ejecutado por política: la verificación automática de Python "
                "está deshabilitada)"
            )
        if self.status == SandboxStatus.UNAVAILABLE:
            return (
                "(no ejecutado: el aislamiento seguro de Python no está disponible; "
                "no se usó ejecución directa)"
            )
        if self.status == SandboxStatus.TIMED_OUT:
            return f"(el código superó el límite de {TIMEOUT_SECONDS}s y fue cancelado)"
        if self.status == SandboxStatus.CANCELED:
            return "(la ejecución del código fue cancelada junto con el job)"
        if self.status == SandboxStatus.POLICY_VIOLATION:
            return "(ejecución bloqueada por la política de aislamiento)"

        output = self.stdout
        if self.stderr:
            output += ("\n--- stderr ---\n" if output else "") + self.stderr
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n…(truncado)"
        elif self.stdout_truncated or self.stderr_truncated:
            output += "\n…(truncado)"

        if self.exit_code is not None and self.exit_code < 0:
            output = (
                "(el código fue cancelado por exceder los límites de recursos "
                f"[señal {-self.exit_code}])\n{output}"
            )
        elif self.status == SandboxStatus.ERROR:
            output = f"(exit code {self.exit_code})\n{output}"
        return output.strip() or "(sin salida)"


@dataclass
class _CaptureBuffer:
    content: bytearray
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        remaining = MAX_CAPTURE_BYTES - len(self.content)
        if remaining > 0:
            self.content.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True


def _limits() -> None:
    """Apply limits before Bubblewrap or the explicit local process starts."""
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (PROCESS_LIMIT, PROCESS_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_LIMIT_BYTES, FILE_LIMIT_BYTES))
    resource.setrlimit(
        resource.RLIMIT_NOFILE,
        (FILE_DESCRIPTOR_LIMIT, FILE_DESCRIPTOR_LIMIT),
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _mode(value: SandboxMode | str | None) -> SandboxMode | None:
    raw = value or os.getenv("PYTHON_SANDBOX_MODE", SandboxMode.DISABLED.value)
    try:
        return SandboxMode(raw)
    except ValueError:
        return None


def _minimal_environment(home: str) -> dict[str, str]:
    return {
        "HOME": home,
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin" if os.name != "nt" else "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def _runtime_mounts() -> list[str]:
    candidates = [
        Path("/usr"),
        Path("/usr/local"),
        Path("/bin"),
        Path("/lib"),
        Path("/lib64"),
        Path(sys.base_prefix).resolve(),
    ]
    mounts: list[str] = []
    for candidate in candidates:
        value = str(candidate)
        if candidate.exists() and value not in mounts:
            mounts.append(value)
    return mounts


def _base_python() -> Path:
    return Path(getattr(sys, "_base_executable", sys.executable)).resolve()


def _isolated_command(work_dir: Path) -> list[str] | None:
    if os.name == "nt":
        return None
    bwrap = shutil.which("bwrap")
    runner = Path(__file__).with_name("sandbox_runner.py").resolve()
    python = _base_python()
    if not bwrap or not runner.is_file() or not python.is_file():
        return None

    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--disable-userns",
        "--clearenv",
        "--cap-drop",
        "ALL",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--size",
        str(WORKSPACE_LIMIT_BYTES),
        "--perms",
        "0700",
        "--tmpfs",
        "/tmp",
        "--size",
        str(WORKSPACE_LIMIT_BYTES),
        "--perms",
        "0700",
        "--tmpfs",
        "/work",
    ]
    runtime_mounts = _runtime_mounts()
    for path in runtime_mounts:
        command.extend(("--ro-bind", path, path))
    command.extend(
        (
            "--dir",
            "/sandbox",
            "--ro-bind",
            str(runner),
            "/sandbox/runner.py",
            "--ro-bind",
            str(work_dir / "snippet.py"),
            "/work/snippet.py",
            "--chdir",
            "/work",
            "--setenv",
            "HOME",
            "/work",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "PATH",
            "/usr/local/bin:/usr/bin:/bin",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "PYTHONIOENCODING",
            "utf-8",
            "--setenv",
            "SANDBOX_RUNTIME_ROOTS",
            os.pathsep.join(runtime_mounts),
            str(python),
            "-I",
            "-B",
            "/sandbox/runner.py",
            "/work/snippet.py",
        )
    )
    return command


def _drain(stream, target: _CaptureBuffer) -> None:
    try:
        while chunk := stream.read(4096):
            target.append(chunk)
    finally:
        stream.close()


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def _run_bounded(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path | None,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None,
) -> tuple[int | None, _CaptureBuffer, _CaptureBuffer, bool, bool]:
    stdout = _CaptureBuffer(bytearray())
    stderr = _CaptureBuffer(bytearray())
    kwargs: dict = {
        "cwd": cwd,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name != "nt":
        kwargs["preexec_fn"] = _limits
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(command, **kwargs)
    stdout_thread = threading.Thread(target=_drain, args=(proc.stdout, stdout), daemon=True)
    stderr_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    canceled = False
    deadline = time.monotonic() + timeout_seconds
    while proc.poll() is None:
        if cancel_requested is not None:
            try:
                should_cancel = cancel_requested()
            except Exception:
                logger.exception("Python sandbox cancellation check failed")
                should_cancel = True
            if should_cancel:
                canceled = True
                _terminate(proc)
                break
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate(proc)
            break
        time.sleep(0.1)
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    return proc.returncode, stdout, stderr, timed_out, canceled


def _decode(value: _CaptureBuffer) -> str:
    return value.content.decode("utf-8", errors="replace")


def _sanitize(text: str, work_dir: Path) -> str:
    cleaned = text.replace(str(work_dir), "<directorio-temporal>")
    cleaned = cleaned.replace("/work/snippet.py", "<snippet>")
    cleaned = cleaned.replace("/sandbox/runner.py", "<sandbox>")
    for root in ("/app", "/data"):
        cleaned = cleaned.replace(root, "<ruta-protegida>")
    return "\n".join(
        line for line in cleaned.splitlines() if not line.startswith(POLICY_MARKER)
    ).strip()


def execute_python_snippet(
    code: str,
    *,
    mode: SandboxMode | str | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    cancel_requested: Callable[[], bool] | None = None,
) -> SandboxResult:
    """Execute code according to the configured policy and return typed details."""
    selected_mode = _mode(mode)
    if selected_mode is None:
        return SandboxResult(status=SandboxStatus.UNAVAILABLE)
    if selected_mode == SandboxMode.DISABLED:
        return SandboxResult(status=SandboxStatus.DISABLED)

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="sandbox-") as tmp:
        work_dir = Path(tmp).resolve()
        snippet = work_dir / "snippet.py"
        snippet.write_text(code, encoding="utf-8")
        try:
            snippet.chmod(0o600)
        except OSError:
            pass

        if selected_mode == SandboxMode.ISOLATED:
            command = _isolated_command(work_dir)
            cwd = None
        else:
            logger.warning(
                "Python sandbox is using explicit local-unsafe mode",
                extra={"sandbox_mode": selected_mode.value},
            )
            command = [sys.executable, "-I", "-B", str(snippet)]
            cwd = work_dir

        if command is None:
            return SandboxResult(
                status=SandboxStatus.UNAVAILABLE,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )

        try:
            exit_code, stdout_buffer, stderr_buffer, timed_out, canceled = _run_bounded(
                command,
                environment=_minimal_environment(str(work_dir)),
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                cancel_requested=cancel_requested,
            )
        except (OSError, subprocess.SubprocessError):
            logger.exception(
                "Python sandbox could not start",
                extra={"sandbox_mode": selected_mode.value},
            )
            return SandboxResult(
                status=SandboxStatus.UNAVAILABLE,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )

        raw_stderr = _decode(stderr_buffer)
        stdout = _sanitize(_decode(stdout_buffer), work_dir)
        stderr = _sanitize(raw_stderr, work_dir)
        policy_violation = POLICY_MARKER in raw_stderr or exit_code == POLICY_EXIT_CODE
        if canceled:
            status = SandboxStatus.CANCELED
        elif timed_out:
            status = SandboxStatus.TIMED_OUT
        elif policy_violation:
            status = SandboxStatus.POLICY_VIOLATION
        elif (
            selected_mode == SandboxMode.ISOLATED
            and exit_code != 0
            and raw_stderr.lstrip().startswith("bwrap:")
        ):
            status = SandboxStatus.UNAVAILABLE
            stdout = ""
            stderr = ""
        elif exit_code == 0:
            status = SandboxStatus.SUCCESS
        else:
            status = SandboxStatus.ERROR

        result = SandboxResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            canceled=canceled,
            policy_violation=policy_violation,
            stdout_truncated=stdout_buffer.truncated,
            stderr_truncated=stderr_buffer.truncated,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        logger.info(
            "Python sandbox execution finished",
            extra={
                "sandbox_mode": selected_mode.value,
                "sandbox_status": result.status.value,
                "duration_ms": result.duration_ms,
                "stdout_size": len(stdout_buffer.content),
                "stderr_size": len(stderr_buffer.content),
                "timed_out": result.timed_out,
                "canceled": result.canceled,
                "policy_violation": result.policy_violation,
            },
        )
        return result


def run_python_snippet(code: str) -> str:
    """Compatibility facade used by the agent tool."""
    return execute_python_snippet(code).render_for_agent()


def build_sandbox_tool(cancel_requested: Callable[[], bool] | None = None):
    from langchain_core.tools import tool

    @tool
    def run_python(code: str) -> str:
        """Verifica Python en aislamiento.

        La respuesta distingue ejecución correcta, fallo del ejemplo y ejemplo no
        ejecutado porque la política o el aislamiento no lo permiten.
        """
        return execute_python_snippet(
            code,
            cancel_requested=cancel_requested,
        ).render_for_agent()

    return run_python
