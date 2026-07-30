import pytest
from factory_api.config import Settings
from pydantic import ValidationError


def test_ffmpeg_settings_defaults_and_overrides():
    defaults = Settings(_env_file=None)
    assert defaults.ffmpeg_threads == 1
    assert defaults.ffmpeg_filter_threads == 1
    assert defaults.ffmpeg_filter_complex_threads == 1
    assert defaults.ffmpeg_preset == "veryfast"
    assert defaults.ffmpeg_crf == 23

    overridden = Settings(
        _env_file=None,
        ffmpeg_threads=2,
        ffmpeg_filter_threads=3,
        ffmpeg_filter_complex_threads=4,
        ffmpeg_preset="fast",
        ffmpeg_crf=18,
    )
    assert overridden.ffmpeg_threads == 2
    assert overridden.ffmpeg_filter_threads == 3
    assert overridden.ffmpeg_filter_complex_threads == 4
    assert overridden.ffmpeg_preset == "fast"
    assert overridden.ffmpeg_crf == 18


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ffmpeg_threads", 0),
        ("ffmpeg_filter_threads", -1),
        ("ffmpeg_filter_complex_threads", 0),
        ("ffmpeg_preset", "turbo"),
        ("ffmpeg_crf", 52),
    ],
)
def test_ffmpeg_settings_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
