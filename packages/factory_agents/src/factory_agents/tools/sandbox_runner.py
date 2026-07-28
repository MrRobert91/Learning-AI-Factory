"""Trusted launcher used only inside the Bubblewrap mount namespace."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

POLICY_EXIT_CODE = 77
POLICY_MARKER = "__SANDBOX_POLICY_VIOLATION__:"
ALLOWED_ROOTS = (
    "/work",
    "/sandbox",
    "/tmp",
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/proc",
    "/dev",
) + tuple(
    root
    for root in os.getenv("SANDBOX_RUNTIME_ROOTS", "").split(os.pathsep)
    if root
)
DENIED_PROCESS_EVENTS = {
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.setns",
    "os.system",
    "os.unshare",
    "pty.spawn",
    "subprocess.Popen",
}

policy_violation: str | None = None


def _deny(reason: str) -> None:
    global policy_violation
    policy_violation = reason
    raise RuntimeError("operación bloqueada por la política de aislamiento")


def _is_allowed_path(value: object) -> bool:
    if isinstance(value, int):
        return True
    try:
        candidate = Path(os.fspath(value))
    except TypeError:
        return False
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    normalized = os.path.normpath(str(candidate))
    return any(normalized == root or normalized.startswith(f"{root}/") for root in ALLOWED_ROOTS)


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and args and not _is_allowed_path(args[0]):
        _deny("filesystem")
    if event.startswith("socket."):
        _deny("network")
    if event in DENIED_PROCESS_EVENTS:
        _deny("process")
    if event == "ctypes.dlopen":
        _deny("native-code")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "/work/snippet.py":
        return POLICY_EXIT_CODE
    sys.addaudithook(_audit)
    try:
        runpy.run_path(sys.argv[1], run_name="__main__")
    except BaseException:
        if policy_violation:
            print(f"{POLICY_MARKER}{policy_violation}", file=sys.stderr)
            return POLICY_EXIT_CODE
        raise
    if policy_violation:
        print(f"{POLICY_MARKER}{policy_violation}", file=sys.stderr)
        return POLICY_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
