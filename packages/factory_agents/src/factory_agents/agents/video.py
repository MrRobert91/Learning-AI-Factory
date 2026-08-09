"""Configurable deterministic video assembly stage."""

from factory_agents.runtime import AgentSpec, register

VIDEO_SPEC = register(
    AgentSpec(
        name="video",
        display_name="Montaje de vídeo",
        description=(
            "Monta de forma determinista slides y audio ya generados, con "
            "orientación y subtítulos configurables."
        ),
        base_prompt="",
        tool_names=("Marp", "ffmpeg"),
        consumes=("slide_deck", "audio"),
        produces=("video",),
        kind="automatic",
    )
)
