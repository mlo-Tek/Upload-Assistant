from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.trackers.UNIT3D.luminarr import Luminarr


def _tracker(default: dict | None = None) -> Luminarr:
    return Luminarr({"DEFAULT": default or {}, "TRACKERS": {"LUMINARR": {}}})


@pytest.mark.asyncio
async def test_english_original_with_german_dub_uses_german_multi() -> None:
    meta = Meta()
    meta.name = "10 Cloverfield Lane 2016 2160p WEB-DL Dual-Audio DD 5.1 DV HDR10+ H.265-VECTOR"
    meta.original_language = "en"
    meta.audio_languages = ["German", "English"]
    meta.is_disc = ""
    meta.tag = "-VECTOR"

    result = await _tracker().get_name(meta)

    assert result["name"] == "10 Cloverfield Lane 2016 2160p WEB-DL German Multi DD 5.1 DV HDR10+ H.265-VECTOR"


@pytest.mark.asyncio
async def test_non_english_original_with_english_dub_keeps_dual_audio() -> None:
    meta = Meta()
    meta.name = "Example 2026 1080p WEB-DL Dual-Audio DD+ 5.1 H.264-GROUP"
    meta.original_language = "ja"
    meta.audio_languages = ["Japanese", "English"]
    meta.is_disc = ""
    meta.tag = "-GROUP"

    result = await _tracker().get_name(meta)

    assert result["name"] == meta.name


@pytest.mark.asyncio
async def test_single_english_audio_does_not_add_multi() -> None:
    meta = Meta()
    meta.name = "Example 2026 1080p WEB-DL DD+ 5.1 H.264-GROUP"
    meta.original_language = "English"
    meta.audio_languages = ["English"]
    meta.is_disc = ""
    meta.tag = "-GROUP"

    result = await _tracker().get_name(meta)

    assert result["name"] == meta.name


@pytest.mark.asyncio
async def test_vector_prefix_without_suffix_adds_vector_group() -> None:
    meta = Meta()
    meta.name = "Hueter des Lichts 2026 1080p BluRay x264"
    meta.category = "MOVIE"
    meta.video = "/data/media/movies/Hueter des Lichts/vector-hueterlicht-1080p.mkv"
    meta.filelist = [meta.video]
    meta.tag = ""

    result = await _tracker().get_name(meta)

    assert result["name"] == "Hueter des Lichts 2026 1080p BluRay x264-VECTOR"


@pytest.mark.asyncio
async def test_missing_filename_group_uses_radarr_release_group() -> None:
    tracker = _tracker(
        {
            "radarr_api_key": "test-key",
            "radarr_url": "http://radarr.invalid:7878",
        }
    )
    tracker.radarr_manager.get_radarr_data = AsyncMock(return_value={"tmdb_id": 123, "release_group": "VECTOR"})

    meta = Meta()
    meta.name = "Waterworld 1995 1080p BluRay x264"
    meta.category = "MOVIE"
    meta.tmdb_id = 123
    meta.video = "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv"
    meta.tag = ""

    result = await tracker.get_name(meta)

    assert result["name"] == "Waterworld 1995 1080p BluRay x264-VECTOR"
    tracker.radarr_manager.get_radarr_data.assert_awaited_once_with(tmdb_id=123)


@pytest.mark.asyncio
async def test_existing_filename_group_wins_without_radarr_lookup() -> None:
    tracker = _tracker(
        {
            "radarr_api_key": "test-key",
            "radarr_url": "http://radarr.invalid:7878",
        }
    )
    tracker.radarr_manager.get_radarr_data = AsyncMock(return_value={"tmdb_id": 123, "release_group": "OTHER"})

    meta = Meta()
    meta.name = "Sisters 2015 1080p BluRay x264-VECTOR"
    meta.category = "MOVIE"
    meta.tmdb_id = 123
    meta.tag = "-VECTOR"

    result = await tracker.get_name(meta)

    assert result["name"] == meta.name
    tracker.radarr_manager.get_radarr_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_tag_disables_automatic_radarr_group() -> None:
    tracker = _tracker(
        {
            "radarr_api_key": "test-key",
            "radarr_url": "http://radarr.invalid:7878",
        }
    )
    tracker.radarr_manager.get_radarr_data = AsyncMock(return_value={"tmdb_id": 123, "release_group": "VECTOR"})

    meta = Meta()
    meta.name = "Mufasa Der Koenig der Loewen 2024 2160p WEB-DL H.265"
    meta.category = "MOVIE"
    meta.tmdb_id = 123
    meta.tag = ""
    meta.no_tag = True

    result = await tracker.get_name(meta)

    assert result["name"] == meta.name
    tracker.radarr_manager.get_radarr_data.assert_not_awaited()
