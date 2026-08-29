from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.trackers.digitalcore import DigitalCore


def _tracker() -> DigitalCore:
    return DigitalCore({"DEFAULT": {}, "TRACKERS": {"DIGITALCORE": {"api_key": "test", "anon": False}}})


@pytest.mark.asyncio
async def test_movie_firstpic_uses_first_uploaded_screenshot() -> None:
    tracker = _tracker()
    meta = Meta()
    meta.category = "MOVIE"
    meta.image_list = [
        {"raw_url": "https://img.example/first.png"},
        {"raw_url": "https://img.example/second.png"},
    ]

    try:
        assert await tracker.get_firstpic(meta) == "https://img.example/first.png"
    finally:
        await tracker.session.aclose()


@pytest.mark.asyncio
async def test_non_scene_release_is_marked_p2p() -> None:
    tracker = _tracker()
    tracker.generate_description = AsyncMock(return_value="description")  # type: ignore[method-assign]
    tracker.mediainfo = AsyncMock(return_value="mediainfo")  # type: ignore[method-assign]

    meta = Meta()
    meta.category = "MOVIE"
    meta.scene_name = ""
    meta.imdb_tt = "tt1179933"
    meta.image_list = [{"raw_url": "https://img.example/first.png"}]

    try:
        data = await tracker.fetch_data(meta)
        assert data["p2p"] == "1"
        assert data["firstpic"] == "https://img.example/first.png"
    finally:
        await tracker.session.aclose()


@pytest.mark.asyncio
async def test_scene_release_is_not_marked_p2p() -> None:
    tracker = _tracker()
    tracker.generate_description = AsyncMock(return_value="description")  # type: ignore[method-assign]
    tracker.mediainfo = AsyncMock(return_value="mediainfo")  # type: ignore[method-assign]

    meta = Meta()
    meta.category = "MOVIE"
    meta.scene_name = "Scene.Release-GROUP"

    try:
        data = await tracker.fetch_data(meta)
        assert data["p2p"] == "0"
    finally:
        await tracker.session.aclose()
