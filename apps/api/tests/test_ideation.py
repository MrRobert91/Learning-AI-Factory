from factory_agents.agents.ideation import AgentEvent


def _fake_turn_factory(script):
    """Returns a run_ideation_turn stand-in that pops events per call."""
    calls = []

    def fake_turn(client, model, history, **kwargs):
        calls.append(list(history))
        return script.pop(0)

    fake_turn.calls = calls
    return fake_turn


def test_ideation_requires_auth(client):
    assert client.post("/api/ideation", json={"idea": "algo de cuántica"}).status_code == 401


def test_ideation_flow(auth_client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    script = [
        [
            AgentEvent(kind="text", content="¡Buena idea! Vamos a afinarla."),
            AgentEvent(
                kind="question",
                content="¿Para qué audiencia?",
                payload={
                    "options": [
                        {"label": "Desarrolladores", "description": "Con código"},
                        {"label": "Negocio", "description": "Sin código"},
                        {"label": "Estudiantes", "description": "Base académica"},
                    ]
                },
            ),
        ],
        [
            AgentEvent(
                kind="brief",
                content="Brief propuesto",
                payload={
                    "working_title": "Cuántica para devs",
                    "topic": "Computación cuántica aplicada",
                    "audience": "Desarrolladores",
                    "level": "intermedio",
                    "language": "es",
                    "style": "práctico",
                    "output_format": "video",
                    "objectives": ["Entender qubits"],
                    "scope_outline": ["Fundamentos", "Algoritmos"],
                    "differential_angle": "Con código real",
                    "open_questions": [],
                },
            ),
        ],
    ]
    fake_turn = _fake_turn_factory(script)
    monkeypatch.setattr("factory_api.routers.ideation.run_ideation_turn", fake_turn)
    monkeypatch.setattr(
        "factory_api.routers.ideation.get_llm_client", lambda key: object()
    )

    # Create session → agent replies with text + question
    resp = auth_client.post("/api/ideation", json={"idea": "algo de cuántica"})
    assert resp.status_code == 201
    session = resp.json()
    session_id = session["id"]
    kinds = [m["kind"] for m in session["messages"]]
    assert kinds == ["text", "text", "question"]
    assert session["messages"][2]["payload"]["options"][0]["label"] == "Desarrolladores"
    assert session["has_brief"] is False

    # Cannot finalize without a brief
    assert auth_client.post(f"/api/ideation/{session_id}/finalize").status_code == 409

    # Answer the question → agent proposes brief
    resp = auth_client.post(
        f"/api/ideation/{session_id}/messages", json={"content": "Desarrolladores"}
    )
    assert resp.status_code == 200
    session = resp.json()
    assert session["has_brief"] is True
    assert session["brief"]["working_title"] == "Cuántica para devs"
    # The user's answer was recorded with kind=answer
    assert any(m["kind"] == "answer" and m["role"] == "user" for m in session["messages"])
    # History passed to the second agent call included the answer
    assert fake_turn.calls[1][-1].kind == "answer"

    # Finalize → creates the project from the brief
    resp = auth_client.post(f"/api/ideation/{session_id}/finalize")
    assert resp.status_code == 200
    project = resp.json()
    assert project["title"] == "Cuántica para devs"
    assert project["audience"] == "Desarrolladores"

    # Session is now finalized and refuses more messages
    resp = auth_client.post(f"/api/ideation/{session_id}/messages", json={"content": "hola"})
    assert resp.status_code == 409

    # Session list shows it linked to the project
    sessions = auth_client.get("/api/ideation").json()
    assert sessions[0]["project_id"] == project["id"]


def test_ideation_without_api_key(auth_client, monkeypatch):
    monkeypatch.setattr(
        "factory_api.routers.ideation.get_settings",
        lambda: __import__("factory_api.config", fromlist=["Settings"]).Settings(
            openrouter_api_key="", app_password="test-password", secret_key="test-secret"
        ),
    )
    resp = auth_client.post("/api/ideation", json={"idea": "algo"})
    assert resp.status_code == 503
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]


def test_ideation_stream_reports_progress(auth_client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    def fake_turn(client, model, history, **kwargs):
        kwargs["on_progress"](
            "tool_call",
            "Consultando fuentes sobre: agentes",
            {"tool": "web_search"},
        )
        return [AgentEvent(kind="text", content="He terminado la comprobación.")]

    monkeypatch.setattr("factory_api.routers.ideation.run_ideation_turn", fake_turn)
    monkeypatch.setattr(
        "factory_api.routers.ideation.get_llm_client", lambda key: object()
    )

    response = auth_client.post("/api/ideation/stream", json={"idea": "curso de agentes"})
    assert response.status_code == 200
    assert "event: progress" in response.text
    assert "Consultando fuentes" in response.text
    assert "event: result" in response.text
