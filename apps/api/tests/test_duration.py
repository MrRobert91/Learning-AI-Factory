from factory_agents.contracts import CoursePlan, DurationSpec
from factory_agents.duration import (
    duration_metrics,
    render_duration_constraints,
    research_budget,
    validate_course_plan_structure,
)


def test_presets_are_canonical_and_totals_are_backend_derived():
    spec = DurationSpec(
        preset="standard",
        module_count=1,
        videos_per_module=1,
        target_minutes_per_video=1,
        total_videos=999,
        total_minutes=999,
    )
    assert spec.module_count == 3
    assert spec.videos_per_module == 4
    assert spec.target_minutes_per_video == 10
    assert spec.total_videos == 12
    assert spec.total_minutes == 120
    assert spec.tolerance_ratio == 0.2


def test_research_and_media_budgets_cover_all_boundaries():
    assert research_budget(5)["searches_max"] == 3
    assert research_budget(6)["brief_words_max"] == 2000
    assert research_budget(31)["sources_min"] == 5
    assert research_budget(91)["searches_max"] == 12
    assert research_budget(301) == {
        "searches_min": 12,
        "searches_max": 12,
        "sources_min": 12,
        "brief_words_max": 6000,
    }
    spec = DurationSpec(
        preset="custom",
        module_count=1,
        videos_per_module=2,
        target_minutes_per_video=8,
    )
    horizontal = duration_metrics(spec)
    vertical = duration_metrics(spec, "vertical")
    assert horizontal["lesson_words"]["target"] == 1200
    assert horizontal["narration_words"]["target"] == 1040
    assert horizontal["slides"]["target"] == 8
    assert vertical["slides"]["target"] == 10
    assert "1 módulos × 2 lecciones" in render_duration_constraints(spec, "planner")


def test_course_plan_structure_is_exact():
    spec = DurationSpec(
        preset="custom",
        module_count=1,
        videos_per_module=2,
        target_minutes_per_video=10,
    )
    plan = CoursePlan(
        course_title="Curso",
        modules=[
            {
                "title": "Módulo",
                "lessons": [
                    {"title": "Uno", "objective": "A"},
                    {"title": "Dos", "objective": "B"},
                ],
            }
        ],
    )
    assert validate_course_plan_structure(plan, spec) == []
    plan.modules[0].lessons.pop()
    assert "debe tener 2 lecciones" in validate_course_plan_structure(plan, spec)[0]


def test_legacy_project_is_blocked_until_duration_is_completed(auth_client):
    project = auth_client.post("/api/projects", json={"title": "Proyecto heredado"}).json()
    assert project["duration_spec"] is None

    response = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={"agent": "planner"},
    )
    assert response.status_code == 409
    assert "duración y estructura" in response.json()["detail"]

    updated = auth_client.patch(
        f"/api/projects/{project['id']}",
        json={
            "duration_spec": {
                "preset": "microvideo",
                "module_count": 5,
                "videos_per_module": 5,
                "target_minutes_per_video": 60,
            }
        },
    )
    assert updated.status_code == 200
    assert updated.json()["duration_spec"]["total_minutes"] == 1


def test_custom_duration_ranges_are_validated(auth_client):
    response = auth_client.post(
        "/api/projects",
        json={
            "title": "Inválido",
            "duration_spec": {
                "preset": "custom",
                "module_count": 0,
                "videos_per_module": 6,
                "target_minutes_per_video": 61,
            },
        },
    )
    assert response.status_code == 422
