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

    result = execute_python_snippet(
        "import hashlib, json, math\n"
        "print(json.dumps({'sum': 2 + 2, 'root': math.isqrt(81), "
        "'hash': hashlib.sha256(b'ok').hexdigest()[:4]}, sort_keys=True))"
    )
    if result.status != SandboxStatus.SUCCESS or '"sum": 4' not in result.stdout:
        raise SystemExit("Normal standard-library snippet did not run")
    require_status("raise ValueError('expected-example-error')", SandboxStatus.ERROR)

    sensitive_paths = (
        Path("/data/db/factory.sqlite"),
        Path("/data/db/checkpoints.sqlite"),
        Path("/app/.env"),
        Path("/app/packages/factory_agents/src/factory_agents/tools/sandbox.py"),
    )
    sentinel_path = Path("/data/sandbox-smoke-secret")
    sentinel_path.write_text("must-not-leak", encoding="utf-8")
    try:
        for path in (*sensitive_paths, sentinel_path):
            result = execute_python_snippet(
                f"print(open({str(path)!r}, 'rb').read(64))",
                timeout_seconds=5,
            )
            if result.status != SandboxStatus.POLICY_VIOLATION:
                raise SystemExit(
                    f"Sensitive path was not blocked: {path}: {result.status.value}"
                )
            if "must-not-leak" in result.stdout or "must-not-leak" in result.stderr:
                raise SystemExit("Sensitive file contents leaked from sandbox")
    finally:
        sentinel_path.unlink(missing_ok=True)

    secret_names = (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_CLIENT_SECRET",
    )
    for name in secret_names:
        os.environ[name] = "must-not-leak"
    result = execute_python_snippet(
        "import os; print([os.getenv(name) for name in "
        "('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_CLIENT_SECRET')])",
        timeout_seconds=5,
    )
    if result.status != SandboxStatus.SUCCESS or "must-not-leak" in result.stdout:
        raise SystemExit("Sandbox inherited a secret environment variable")

    for target in ("127.0.0.1", "10.0.0.1", "1.1.1.1"):
        require_status(
            "import socket\n"
            f"socket.create_connection(({target!r}, 443), timeout=0.1)",
            SandboxStatus.POLICY_VIOLATION,
        )
    require_status(
        "import socket; socket.socket(type=socket.SOCK_DGRAM)",
        SandboxStatus.POLICY_VIOLATION,
    )
    require_status(
        "import subprocess; subprocess.run(['python', '-c', 'print(1)'])",
        SandboxStatus.POLICY_VIOLATION,
    )
    require_status("import os; os.fork()", SandboxStatus.POLICY_VIOLATION)
    require_status("while True: pass", SandboxStatus.TIMED_OUT, timeout=0.5)

    result = execute_python_snippet(
        "while True: print('x' * 4096)",
        timeout_seconds=0.5,
    )
    if result.status != SandboxStatus.TIMED_OUT or not result.stdout_truncated:
        raise SystemExit("Sandbox output capture was not bounded")

    result = execute_python_snippet(
        "chunks = []\n"
        "while True:\n"
        "    chunks.append(bytearray(16_000_000))\n",
        timeout_seconds=5,
    )
    if result.status == SandboxStatus.SUCCESS:
        raise SystemExit("Sandbox memory limit was not enforced")

    result = execute_python_snippet(
        "open('oversized.bin', 'wb').write(b'x' * 2_000_000)",
        timeout_seconds=5,
    )
    if result.status == SandboxStatus.SUCCESS:
        raise SystemExit("Sandbox file-size limit was not enforced")

    result = execute_python_snippet(
        "from pathlib import Path\n"
        "for index in range(129):\n"
        "    Path(f'bulk-{index}').write_text('x')\n",
        timeout_seconds=5,
    )
    if result.status == SandboxStatus.SUCCESS:
        raise SystemExit("Sandbox writable workspace exceeded its quota")

    print("Python sandbox container verification passed")


if __name__ == "__main__":
    main()
