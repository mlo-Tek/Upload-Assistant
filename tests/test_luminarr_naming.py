import pytest

from src.meta import Meta
from src.trackers.UNIT3D.luminarr import Luminarr


def _tracker() -> Luminarr:
    return Luminarr({"TRACKERS": {"LUMINARR": {}}})


@pytest.mark.asyncio
async def test_english_original_with_german_dub_uses_german_multi() -> None:
    meta = Meta()
    meta.name = "10 Cloverfield Lane 2016 2160p WEB-DL Dual-Audio DD 5.1 DV HDR10+ H.265-VECTOR"
    meta.original_language = "en"
    meta.audio_languages = ["German", "English"]
    meta.is_disc = ""

    result = await _tracker().get_name(meta)

    assert result["name"] == "10 Cloverfield Lane 2016 2160p WEB-DL German Multi DD 5.1 DV HDR10+ H.265-VECTOR"


@pytest.mark.asyncio
async def test_non_english_original_with_english_dub_keeps_dual_audio() -> None:
    meta = Meta()
    meta.name = "Example 2026 1080p WEB-DL Dual-Audio DD+ 5.1 H.264-GROUP"
    meta.original_language = "ja"
    meta.audio_languages = ["Japanese", "English"]
    meta.is_disc = ""

    result = await _tracker().get_name(meta)

    assert result["name"] == meta.name


@pytest.mark.asyncio
async def test_single_english_audio_does_not_add_multi() -> None:
    meta = Meta()
    meta.name = "Example 2026 1080p WEB-DL DD+ 5.1 H.264-GROUP"
    meta.original_language = "English"
    meta.audio_languages = ["English"]
    meta.is_disc = ""

    result = await _tracker().get_name(meta)

    assert result["name"] == meta.name
