"""Regression tests for release-group extraction."""

import pytest

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
async def test_long_release_group_is_preserved_without_scene_detection():
    filename = "The.Movie.2011.1080p.WEB-DL.DD2.0.H.264-10GaugeSlugBlaster.mkv"

    tag = await get_tag(filename, Meta(category="MOVIE", uuid=filename))

    assert tag == "-10GaugeSlugBlaster"


@pytest.mark.asyncio
async def test_folder_tag_replaces_the_bogus_tag_of_a_lowercase_scene_file(tmp_path):
    from src.tags import prefer_folder_tag

    folder = tmp_path / "A.Quiet.Place.2.2021.German.EAC3D.Atmos.DL.2160p.UHD.BluRay.DV.HDR.x265-VECTOR"
    folder.mkdir()
    video = folder / "vector-quietplace2.2160p.dv.mkv"
    video.write_bytes(b"video")
    meta = Meta(category="MOVIE", uuid=folder.name, path=str(folder), isdir=True)

    file_tag = await get_tag(str(video), meta)
    assert file_tag == "-quietplace2.2160p.dv"
    assert await prefer_folder_tag(str(video), meta, file_tag) == "-VECTOR"


@pytest.mark.asyncio
async def test_file_tag_is_kept_when_the_folder_has_no_usable_group(tmp_path):
    from src.tags import prefer_folder_tag

    folder = tmp_path / "Fictional.Movie.2020.1080p.BluRay.x264"
    folder.mkdir()
    video = folder / "Fictional.Movie.2020.1080p.BluRay.x264-GRP.mkv"
    video.write_bytes(b"video")
    meta = Meta(category="MOVIE", uuid=folder.name, path=str(folder), isdir=True)

    assert await prefer_folder_tag(str(video), meta, "-GRP") == "-GRP"


@pytest.mark.asyncio
async def test_folder_tag_is_only_used_for_folders(tmp_path):
    from src.tags import prefer_folder_tag

    video = tmp_path / "vector-quietplace2.2160p.dv.mkv"
    video.write_bytes(b"video")
    meta = Meta(category="MOVIE", uuid=video.name, path=str(video), isdir=False)

    assert await prefer_folder_tag(str(video), meta, "-quietplace2.2160p.dv") == "-quietplace2.2160p.dv"
