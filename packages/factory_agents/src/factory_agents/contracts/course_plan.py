from pydantic import BaseModel, Field


class LessonPlan(BaseModel):
    title: str
    objective: str = Field(description="Qué sabrá hacer el estudiante al terminar")
    key_points: list[str] = Field(default_factory=list)
    estimated_minutes: int = Field(default=10, ge=1, le=120)


class ModulePlan(BaseModel):
    title: str
    summary: str = ""
    lessons: list[LessonPlan] = Field(default_factory=list)


class CoursePlan(BaseModel):
    """Course structure produced by the course designer agent."""

    course_title: str
    summary: str = ""
    audience: str = ""
    level: str = ""
    language: str = "es"
    prerequisites: list[str] = Field(default_factory=list)
    modules: list[ModulePlan] = Field(default_factory=list)

    def iter_lessons(self):
        """Yield (module_index, lesson_index, module, lesson) in course order."""
        for mi, module in enumerate(self.modules, start=1):
            for li, lesson in enumerate(module.lessons, start=1):
                yield mi, li, module, lesson
