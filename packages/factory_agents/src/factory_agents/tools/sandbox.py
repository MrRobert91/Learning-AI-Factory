"""Limited code sandbox: runs Python snippets in an isolated subprocess.

Isolation is best-effort within the single-container constraint: isolated
mode (-I), a throwaway temp dir as cwd, a minimal environment, wall-clock
timeout and CPU/memory rlimits. It is NOT a security boundary against a
hostile actor — it validates didactic snippets written by our own agents.
"""

import os
import subprocess
import sys
import tempfile

TIMEOUT_SECONDS = 15
MAX_OUTPUT_CHARS = 4000
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
CPU_SECONDS = 10

if os.name != "nt":
    import resource


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def run_python_snippet(code: str) -> str:
    """Execute a Python snippet and return its combined output."""
    with tempfile.TemporaryDirectory(prefix="sandbox-") as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=tmp,
                env={"PATH": "", "HOME": tmp},
                preexec_fn=_limits if os.name != "nt" else None,
            )
        except subprocess.TimeoutExpired:
            return f"(el código superó el límite de {TIMEOUT_SECONDS}s y fue cancelado)"
        except Exception as exc:
            return f"(no se pudo ejecutar el código: {exc})"

    output = proc.stdout
    if proc.stderr:
        output += ("\n--- stderr ---\n" if output else "") + proc.stderr
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n…(truncado)"
    if proc.returncode < 0:
        output = (
            f"(el código fue cancelado por exceder los límites de recursos "
            f"[señal {-proc.returncode}])\n{output}"
        )
    elif proc.returncode != 0:
        output = f"(exit code {proc.returncode})\n{output}"
    return output.strip() or "(sin salida)"


def build_sandbox_tool():
    from langchain_core.tools import tool

    @tool
    def run_python(code: str) -> str:
        """Ejecuta un fragmento de código Python y devuelve su salida (stdout/stderr).
        Úsalo para verificar que los ejemplos de código de la lección funcionan."""
        return run_python_snippet(code)

    return run_python
