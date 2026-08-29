"""Regression tests for release-group extraction."""

import pytest

import src.radarr as radarr_module
import src.tags as tags_module
from src.get_name import NameManager
from src.meta import Meta
from src.tags import get_tag


@pytest.mark.parametrize(
    "filename",
    [
        "Movie.2005.1080p.WEB-DL.mkv",
        "Movie.2005.1080p.Blu-ray.mkv",
    ],
)
@pytest.mark.asyncio
async def test_technical_hyphens_are_not_release_group_separators(filename):
    tag = await get_tag(filename, Meta(category="MOVIE", uuid=filename))

    assert tag == ""


@pytest.mark.asyncio
async def test_dts_hd_audio_is_not_treated_as_a_release_group():
    filename = "Example Movie 2005 1080p BluRay REMUX AVC DTS-HD MA 5.1.mkv"
    tag = await get_tag(filename, Meta(category="MOVIE", uuid=filename))

    assert tag == ""

    name_meta = Meta(
        category="MOVIE",
        type="REMUX",
        source="BluRay",
        title="Example Movie",
        year=2005,
        resolution="1080p",
        uhd="",
        video_codec="AVC",
        audio="DTS-HD MA 5.1",
        tag=tag,
    )
    _name_notag, name, _clean_name, _potential_missing = await NameManager({}).get_name(name_meta)

    assert name == "Example Movie 2005 1080p BluRay REMUX AVC DTS-HD MA 5.1"


@pytest.mark.asyncio
async def test_release_group_after_dts_hd_audio_is_preserved():
    filename = "Movie.2005.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-GROUP.mkv"

    tag = await get_tag(filename, Meta(category="MOVIE", uuid=filename))

    assert tag == "-GROUP"


@pytest.mark.asyncio
async def test_vector_prefix_is_recognized_globally():
    filename = "vector-hueterlicht-1080p.mkv"

    tag = await get_tag(filename, Meta(category="MOVIE", uuid=filename))

    assert tag == "-VECTOR"


@pytest.mark.asyncio
async def test_groupless_movie_uses_radarr_release_group(monkeypatch):
    calls: list[int] = []

    class FakeRadarrManager:
        def __init__(self, _config):
            pass

        async def get_radarr_data(self, tmdb_id=None, filename=None):
            calls.append(tmdb_id)
            return {"tmdb_id": tmdb_id, "release_group": "VECTOR"}

    monkeypatch.setattr(
        tags_module,
        "_runtime_config",
        lambda: {
            "DEFAULT": {
                "use_radarr": True,
                "radarr_api_key": "test-key",
                "radarr_url": "http://radarr.invalid:7878",
            }
        },
    )
    monkeypatch.setattr(radarr_module, "RadarrManager", FakeRadarrManager)

    meta = Meta(category="MOVIE", tmdb_id=123, uuid="Waterworld.1995.mkv")
    tag = await get_tag("Waterworld.1995.mkv", meta)

    assert tag == "-VECTOR"
    assert calls == [123]


@pytest.mark.asyncio
async def test_filename_group_wins_over_radarr_fallback(monkeypatch):
    def fail_runtime_config():
        raise AssertionError("Radarr fallback must not run when the filename contains a group")

    monkeypatch.setattr(tags_module, "_runtime_config", fail_runtime_config)

    meta = Meta(category="MOVIE", tmdb_id=123, uuid="Sisters.2015-GROUP.mkv")
    tag = await get_tag("Sisters.2015.German.DTS.DL.1080p.BluRay.x264-VECTOR.mkv", meta)

    assert tag == "-VECTOR"


@pytest.mark.asyncio
async def test_no_tag_disables_arr_release_group_fallback(monkeypatch):
    def fail_runtime_config():
        raise AssertionError("*arr fallback must not run with --no-tag")

    monkeypatch.setattr(tags_module, "_runtime_config", fail_runtime_config)

    meta = Meta(category="MOVIE", tmdb_id=123, uuid="Mufasa.2024.mkv")
    meta.no_tag = True

    tag = await get_tag("Mufasa-Der.Koenig.der.Loewen.2024.mkv", meta)

    assert tag == ""
