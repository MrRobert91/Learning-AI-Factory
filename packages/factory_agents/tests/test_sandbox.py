import os
import shutil

import pytest
from factory_agents.tools.sandbox import (
    MAX_CAPTURE_BYTES,
    SandboxMode,
    SandboxStatus,
    execute_python_snippet,
    run_python_snippet,
)


def test_sandbox_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PYTHON_SANDBOX_MODE", raising=False)

    result = execute_python_snippet("raise AssertionError('must not run')")

    assert result.status == SandboxStatus.DISABLED
    assert result.exit_code is None
    assert "no ejecutado por política" in result.render_for_agent()


def test_invalid_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("PYTHON_SANDBOX_MODE", "automatic")

    result = execute_python_snippet("print('must not run')")

    assert result.status == SandboxStatus.UNAVAILABLE
    assert "no se usó ejecución directa" in result.render_for_agent()


def test_explicit_local_unsafe_mode_runs_code():
    result = execute_python_snippet("print(2 + 2)", mode=SandboxMode.LOCAL_UNSAFE)

    assert result.status == SandboxStatus.SUCCESS
    assert result.stdout == "4"
    assert result.stderr == ""


def test_explicit_local_unsafe_mode_captures_errors():
    result = execute_python_snippet(
        "raise ValueError('boom')",
        mode=SandboxMode.LOCAL_UNSAFE,
    )

    assert result.status == SandboxStatus.ERROR
    assert result.exit_code
    assert "boom" in result.render_for_agent()
    assert "sandbox-" not in result.render_for_agent()


def test_explicit_local_unsafe_mode_times_out():
    result = execute_python_snippet(
        "while True: pass",
        mode=SandboxMode.LOCAL_UNSAFE,
        timeout_seconds=0.2,
    )

    assert result.status == SandboxStatus.TIMED_OUT
    assert result.timed_out is True
    assert "cancelado" in result.render_for_agent()


def test_cancel_request_stops_running_process():
    result = execute_python_snippet(
        "while True: pass",
        mode=SandboxMode.LOCAL_UNSAFE,
        timeout_seconds=5,
        cancel_requested=lambda: True,
    )

    assert result.status == SandboxStatus.CANCELED
    assert result.canceled is True
    assert result.timed_out is False
    assert "cancelada junto con el job" in result.render_for_agent()


def test_capture_is_bounded_while_process_runs():
    result = execute_python_snippet(
        "print('x' * 100_000)",
        mode=SandboxMode.LOCAL_UNSAFE,
    )

    assert result.status == SandboxStatus.SUCCESS
    assert result.stdout_truncated is True
    assert len(result.stdout.encode()) <= MAX_CAPTURE_BYTES
    assert "truncado" in result.render_for_agent()


def test_public_facade_uses_configured_policy(monkeypatch):
    monkeypatch.setenv("PYTHON_SANDBOX_MODE", "disabled")

    assert "no ejecutado por política" in run_python_snippet("print(4)")


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="Bubblewrap integration is validated in the backend container",
)
def test_isolated_mode_runs_and_blocks_network_and_host_paths():
    success = execute_python_snippet("print(2 + 2)", mode=SandboxMode.ISOLATED)
    filesystem = execute_python_snippet(
        "print(open('/data/db/factory.sqlite', 'rb').read(8))",
        mode=SandboxMode.ISOLATED,
    )
    network = execute_python_snippet(
        "import socket; socket.socket()",
        mode=SandboxMode.ISOLATED,
    )

    assert success.status == SandboxStatus.SUCCESS
    assert success.stdout == "4"
    assert filesystem.status == SandboxStatus.POLICY_VIOLATION
    assert filesystem.policy_violation is True
    assert network.status == SandboxStatus.POLICY_VIOLATION
    assert network.policy_violation is True
