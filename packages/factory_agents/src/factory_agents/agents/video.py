"""Configurable automatic video assembly stage."""

from factory_agents.runtime import AgentSpec, register

VIDEO_SPEC = register(
    AgentSpec(
        name="video",
        display_name="Montaje de vídeo",
        description=(
            "Sintetiza la narración, renderiza las slides y monta el vídeo "
            "en formato horizontal o vertical."
        ),
        base_prompt="",
        tool_names=("TTS", "Marp", "ffmpeg"),
        consumes=("voice_script", "slide_deck"),
        produces=("video", "subtitles"),
        kind="automatic",
    )
)
