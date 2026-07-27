from typing import Literal

from pydantic import BaseModel, Field

from factory_agents.contracts.duration_spec import DurationSpec


class CourseIdeaBrief(BaseModel):
    """Refined course specification produced by the Ideation Assistant.

    This is the entry artifact of the pipeline: it becomes the project's
    parameters and the input of the content curator agent.
    """

    working_title: str = Field(description="Título de trabajo del curso")
    topic: str = Field(description="Tema afinado: qué se enseña y con qué enfoque")
    audience: str = Field(description="Audiencia objetivo y conocimientos previos asumidos")
    level: str = Field(description="Nivel de profundidad: introductorio, intermedio o avanzado")
    language: str = Field(default="es", description="Idioma del curso (código ISO: es, en…)")
    style: str = Field(default="", description="Estilo y tono del curso")
    output_format: str = Field(
        default="video", description="Formato de salida deseado: video, slides o script"
    )
    duration_spec: DurationSpec = Field(
        description="Duración y estructura exactas elegidas por el usuario"
    )
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"] = "web_only"
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    objectives: list[str] = Field(
        default_factory=list, description="Objetivos de aprendizaje concretos"
    )
    scope_outline: list[str] = Field(
        default_factory=list, description="Alcance orientativo: grandes bloques o módulos"
    )
    differential_angle: str = Field(
        default="", description="Ángulo diferencial frente a cursos existentes"
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Cuestiones que quedaron abiertas y deberá resolver la investigación",
    )
