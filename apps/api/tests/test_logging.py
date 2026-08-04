import io
import logging

from factory_api.config import get_settings
from factory_api.logging_config import HumanReadableFormatter, configure_logging
from factory_api.main import log_request
from factory_api.runner import _event_log_data, _event_log_summary
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _record(message: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        "factory_api.runner",
        logging.INFO,
        __file__,
        1,
        message,
        (),
        None,
    )
    record.created = 1_785_236_535
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_human_formatter_is_readable_unicode_and_abbreviates_ids():
    output = HumanReadableFormatter().format(
        _record(
            "Lección completada",
            category="STEP",
            job_id="12345678-1234-1234-1234-123456789abc",
            profile_version=3,
            duration_ms=842.4,
        )
    )

    assert "| INFO    | STEP     | Lección completada" in output
    assert "job=12345678" in output
    assert "profile_version=3" in output
    assert "duration_ms=842.4" in output
    assert not output.lstrip().startswith("{")


def test_human_formatter_redacts_secrets_and_sensitive_content():
    output = HumanReadableFormatter().format(
        _record(
            (
                "Provider failed Bearer private-token api_key=super-secret "
                "sk-private123 https://provider.test?token=query-secret"
            ),
            category="TTS",
            prompt="full prompt",
            payload={"document": "private course", "model": "voice-model"},
        )
    )

    assert "private-token" not in output
    assert "super-secret" not in output
    assert "sk-private123" not in output
    assert "query-secret" not in output
    assert "full prompt" not in output
    assert "private course" not in output
    assert "Bearer [redacted]" in output
    assert "[redacted]" in output


def test_human_formatter_keeps_multiline_tracebacks():
    try:
        raise RuntimeError("fallo legible")
    except RuntimeError:
        record = _record("FAIL example", category="JOB")
        record.levelno = logging.ERROR
        record.levelname = "ERROR"
        record.exc_info = __import__("sys").exc_info()

    output = HumanReadableFormatter().format(record)

    assert "| ERROR   | JOB      | FAIL example" in output
    assert "\nTraceback (most recent call last):" in output
    assert "RuntimeError: fallo legible" in output


def test_agent_event_logging_does_not_copy_generated_content_or_feedback():
    generated = "respuesta completa que no debe aparecer"
    feedback = "feedback privado que tampoco debe aparecer"

    assert _event_log_summary("assistant", generated, {}) == "Agent tool activity"
    assert (
        feedback
        not in _event_log_summary(
            "evaluation",
            feedback,
            {"agent": "slides", "status": "done", "verdict": "pass"},
        )
    )
    assert "feedback" not in _event_log_data({"feedback": feedback, "agent": "slides"})


def test_configure_logging_uses_console_only_and_disables_uvicorn_access():
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    previous_access = (
        list(access_logger.handlers),
        access_logger.disabled,
        access_logger.propagate,
    )
    stream = io.StringIO()
    try:
        configure_logging("INFO", stream=stream)
        logging.getLogger("factory_api.main").info(
            "GET /api/health -> 200",
            extra={"category": "HTTP", "request_id": "abcdef1234567890"},
        )

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)
        assert "RotatingFileHandler" not in type(root.handlers[0]).__name__
        assert access_logger.disabled is True
        assert access_logger.propagate is False
        assert "| HTTP     | GET /api/health -> 200" in stream.getvalue()
    finally:
        root.handlers[:] = previous_handlers
        root.setLevel(previous_level)
        access_logger.handlers[:] = previous_access[0]
        access_logger.disabled = previous_access[1]
        access_logger.propagate = previous_access[2]


def test_http_middleware_logs_2xx_4xx_and_5xx_once():
    test_app = FastAPI()
    test_app.middleware("http")(log_request)

    @test_app.get("/ok")
    def ok():
        return {"status": "ok"}

    @test_app.get("/failure")
    def failure():
        raise RuntimeError("provider failed safely")

    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    stream = io.StringIO()
    try:
        configure_logging("INFO", stream=stream)
        with TestClient(test_app, raise_server_exceptions=False) as test_client:
            assert test_client.get("/ok").status_code == 200
            assert test_client.get("/missing").status_code == 404
            assert test_client.get("/failure").status_code == 500

        output = stream.getvalue()
        assert output.count("| HTTP     | GET /ok -> 200 |") == 1
        assert output.count("| HTTP     | GET /missing -> 404 |") == 1
        assert output.count("| HTTP     | GET /failure -> 500 |") == 1
        assert "RuntimeError: provider failed safely" in output
    finally:
        root.handlers[:] = previous_handlers
        root.setLevel(previous_level)


def test_backend_does_not_create_jsonl_log(client):
    assert client.get("/api/health").status_code == 200
    assert not (get_settings().data_dir / "logs" / "backend.jsonl").exists()
