import math

from factory_agents.contracts.duration_spec import DurationSpec


def research_budget(total_minutes: int) -> dict[str, int]:
    if total_minutes <= 5:
        return {"searches_min": 1, "searches_max": 3, "sources_min": 2, "brief_words_max": 1000}
    if total_minutes <= 30:
        return {"searches_min": 3, "searches_max": 5, "sources_min": 3, "brief_words_max": 2000}
    if total_minutes <= 90:
        return {"searches_min": 5, "searches_max": 8, "sources_min": 5, "brief_words_max": 3500}
    if total_minutes <= 300:
        return {"searches_min": 8, "searches_max": 12, "sources_min": 8, "brief_words_max": 5000}
    return {"searches_min": 12, "searches_max": 12, "sources_min": 12, "brief_words_max": 6000}


def target_range(target: int, tolerance_ratio: float = 0.2) -> tuple[int, int]:
    return (
        max(1, math.floor(target * (1 - tolerance_ratio))),
        max(1, math.ceil(target * (1 + tolerance_ratio))),
    )


def duration_metrics(spec: DurationSpec, orientation: str = "horizontal") -> dict:
    lesson_words = spec.target_minutes_per_video * 150
    narration_words = spec.target_minutes_per_video * 130
    slide_rate = 1.25 if orientation == "vertical" else 1.0
    slide_target = max(1, round(spec.target_minutes_per_video * slide_rate))
    return {
        "research": research_budget(spec.total_minutes),
        "lesson_words": {
            "target": lesson_words,
            "min": target_range(lesson_words, spec.tolerance_ratio)[0],
            "max": target_range(lesson_words, spec.tolerance_ratio)[1],
        },
        "narration_words": {
            "target": narration_words,
            "min": target_range(narration_words, spec.tolerance_ratio)[0],
            "max": target_range(narration_words, spec.tolerance_ratio)[1],
        },
        "slides": {
            "target": slide_target,
            "min": target_range(slide_target, spec.tolerance_ratio)[0],
            "max": target_range(slide_target, spec.tolerance_ratio)[1],
            "orientation": orientation,
        },
    }


def render_duration_constraints(
    spec: DurationSpec, agent: str, orientation: str = "horizontal"
) -> str:
    metrics = duration_metrics(spec, orientation)
    header = (
        "# Restricciones estructurales del proyecto (obligatorias)\n"
        f"- Preset: {spec.preset}\n"
        f"- Estructura exacta: {spec.module_count} módulos × "
        f"{spec.videos_per_module} lecciones por módulo = {spec.total_videos} vídeos\n"
        f"- Duración objetivo: {spec.target_minutes_per_video} min por vídeo; "
        f"{spec.total_minutes} min en total; tolerancia ±20 %\n"
    )
    if agent == "curator":
        budget = metrics["research"]
        return header + (
            f"- Investigación: {budget['searches_min']}–{budget['searches_max']} búsquedas, "
            f"mínimo {budget['sources_min']} fuentes y brief de hasta "
            f"{budget['brief_words_max']} palabras.\n"
            "- No superes el máximo de búsquedas aunque consideres que el tema admite más."
        )
    if agent == "planner":
        return header + (
            "- El JSON debe contener exactamente esa cantidad de módulos y lecciones.\n"
            f"- Cada lección debe declarar {spec.target_minutes_per_video} minutos objetivo "
            "(se admite ±20 % en la duración final, no en la estructura)."
        )
    if agent == "lessons":
        words = metrics["lesson_words"]
        return header + (
            f"- Contenido por lección: objetivo {words['target']} palabras "
            f"(rango orientativo {words['min']}–{words['max']}).\n"
            "- Ajusta la densidad al tiempo disponible; no recortes una respuesta ya generada."
        )
    if agent == "slides":
        slides = metrics["slides"]
        return header + (
            f"- Slides por lección {orientation}: objetivo {slides['target']} "
            f"(rango orientativo {slides['min']}–{slides['max']}, nunca menos de una).\n"
            "- Reparte contenido denso en slides adicionales sin convertirlas en muros de texto."
        )
    if agent in {"script", "voice"}:
        words = metrics["narration_words"]
        return header + (
            f"- Narración por lección a 130 palabras/min: objetivo {words['target']} palabras "
            f"(rango {words['min']}–{words['max']}).\n"
            "- Conserva un bloque/segmento por slide y ajusta la densidad al tiempo."
        )
    return header


def validate_course_plan_structure(plan, spec: DurationSpec) -> list[str]:
    problems: list[str] = []
    minimum_minutes, maximum_minutes = target_range(
        spec.target_minutes_per_video, spec.tolerance_ratio
    )
    if len(plan.modules) != spec.module_count:
        problems.append(
            f"se esperaban {spec.module_count} módulos y se recibieron {len(plan.modules)}"
        )
    for index, module in enumerate(plan.modules, start=1):
        if len(module.lessons) != spec.videos_per_module:
            problems.append(
                f"el módulo {index} debe tener {spec.videos_per_module} lecciones "
                f"y tiene {len(module.lessons)}"
            )
        for lesson_index, lesson in enumerate(module.lessons, start=1):
            if not minimum_minutes <= lesson.estimated_minutes <= maximum_minutes:
                problems.append(
                    f"la lección {index}.{lesson_index} declara "
                    f"{lesson.estimated_minutes} min; debe estar entre "
                    f"{minimum_minutes} y {maximum_minutes}"
                )
    return problems
