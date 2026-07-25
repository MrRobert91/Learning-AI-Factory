"""Artifact contracts: the typed inputs/outputs exchanged between agents.

Defined incrementally as each agent lands (see docs/PLAN.md section 5).
"""

from factory_agents.contracts.course_idea_brief import CourseIdeaBrief
from factory_agents.contracts.course_plan import CoursePlan, LessonPlan, ModulePlan
from factory_agents.contracts.duration_spec import DURATION_PRESETS, DurationSpec
from factory_agents.contracts.voice_script import VoiceScript, VoiceSegment

__all__ = [
    "CourseIdeaBrief",
    "CoursePlan",
    "DURATION_PRESETS",
    "DurationSpec",
    "LessonPlan",
    "ModulePlan",
    "VoiceScript",
    "VoiceSegment",
]
