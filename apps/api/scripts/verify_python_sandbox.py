"""Container smoke test for the generated-Python security boundary."""

from __future__ import annotations

import os
from pathlib import Path

from factory_agents.tools.sandbox import SandboxStatus, execute_python_snippet


def require_status(code: str, status: SandboxStatus, *, timeout: float = 5) -> None:
    result = execute_python_snippet(code, timeout_seconds=timeout)
    if result.status != status:
        raise SystemExit(
            f"Expected sandbox status {status.value}, got {result.status.value}: "
            f"{result.render_for_agent()}"
        )


def main() -> None:
    if os.getuid() == 0:
        raise SystemExit("Backend container must not run as root")

    require_status("print(2 + 2)", SandboxStatus.SUCCESS)

    secret_path = Path("/data/sandbox-smoke-secret")
    secret_path.write_text("must-not-leak", encoding="utf-8")
    try:
        result = execute_python_snippet(
            "print(open('/data/sandbox-smoke-secret').read())",
            timeout_seconds=5,
        )
        if result.status != SandboxStatus.POLICY_VIOLATION:
            raise SystemExit(f"Sensitive path was not blocked: {result.status.value}")
        if "must-not-leak" in result.stdout or "must-not-leak" in result.stderr:
            raise SystemExit("Sensitive file contents leaked from sandbox")
    finally:
        secret_path.unlink(missing_ok=True)

    os.environ["OPENROUTER_API_KEY"] = "must-not-leak"
    result = execute_python_snippet(
        "import os; print(os.getenv('OPENROUTER_API_KEY'))",
        timeout_seconds=5,
    )
    if result.status != SandboxStatus.SUCCESS or result.stdout != "None":
        raise SystemExit("Sandbox inherited a secret environment variable")

    require_status("import socket; socket.socket()", SandboxStatus.POLICY_VIOLATION)
    require_status(
        "import subprocess; subprocess.run(['python', '-c', 'print(1)'])",
        SandboxStatus.POLICY_VIOLATION,
    )
    require_status("while True: pass", SandboxStatus.TIMED_OUT, timeout=0.5)

    result = execute_python_snippet("print('x' * 100_000)", timeout_seconds=5)
    if result.status != SandboxStatus.SUCCESS or not result.stdout_truncated:
        raise SystemExit("Sandbox output capture was not bounded")

    result = execute_python_snippet(
        "from pathlib import Path\n"
        "for index in range(64):\n"
        "    Path(f'bulk-{index}').write_bytes(b'x' * 1_000_000)\n",
        timeout_seconds=5,
    )
    if result.status == SandboxStatus.SUCCESS:
        raise SystemExit("Sandbox writable workspace exceeded its quota")

    print("Python sandbox container verification passed")


if __name__ == "__main__":
    main()
