"""Regression tests for DarkPeers rule 4.12 original-release naming."""

import asyncio
from unittest.mock import AsyncMock

from src.meta import Meta
from src.trackers.UNIT3D.darkpeers import DarkPeers


ORIGINAL = "Waterworld.1995.German.DTSX.DL.2160p.UHD.UK.BluRay.DV.HDR.x265-VECTOR"
GENERATED = "Waterworld 1995 2160p UHD BluRay Dual-Audio DTS:X 7.1 DV HDR x265-VECTOR"
CURRENT_PATH = "/data/media/movies/Waterworld (1995) [tmdb-9804]/Waterworld.1995.mkv"


def _adapter() -> DarkPeers:
    return DarkPeers(
        {
            "DEFAULT": {
                "tmdb_api": "test-key",
                "use_radarr": True,
                "radarr_url": "http://radarr:7878",
                "radarr_api_key": "secret",
            },
            "TRACKERS": {"DARKPEERS": {}},
        }
    )


def test_darkpeers_movie_uses_exact_original_release_name_without_retagging() -> None:
    adapter = _adapter()
    adapter._resolve_original_movie_name = AsyncMock(return_value=ORIGINAL)
    meta = Meta(
        category="MOVIE",
        tmdb_id=9804,
        name=GENERATED,
        language_checked=True,
        original_language="English",
        audio_languages=["German", "English"],
    )

    assert asyncio.run(adapter.get_name(meta))["name"] == ORIGINAL


def test_darkpeers_blocks_radarr_movie_when_original_name_cannot_be_recovered() -> None:
    adapter = _adapter()
    adapter._resolve_original_movie_name = AsyncMock(return_value="")
    meta = Meta(
        category="MOVIE",
        tmdb_id=9804,
        name=GENERATED,
        unattended=True,
        language_checked=True,
        original_language="English",
        audio_languages=["German", "English"],
        resolution="2160p",
        screens=4,
    )

    assert asyncio.run(adapter.get_additional_checks(meta)) is False


def test_darkpeers_history_prefers_exact_current_import_path() -> None:
    history = [
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": "Other.Movie.2026.2160p-WRONG",
            "data": {"importedPath": "/data/media/movies/Other Movie (2026)/Other.Movie.mkv"},
        },
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": ORIGINAL,
            "data": {"importedPath": CURRENT_PATH},
        },
    ]

    assert (
        DarkPeers._history_source_title(
            history,
            CURRENT_PATH,
            allow_latest_import_fallback=False,
        )
        == ORIGINAL
    )


def test_darkpeers_history_ignores_newer_stripped_exact_import_when_group_is_known() -> None:
    history = [
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": "Waterworld.1995",
            "data": {"importedPath": CURRENT_PATH},
        },
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": ORIGINAL,
            "data": {"importedPath": CURRENT_PATH},
        },
    ]

    assert (
        DarkPeers._history_source_title(
            history,
            CURRENT_PATH,
            allow_latest_import_fallback=False,
            expected_group="VECTOR",
        )
        == ORIGINAL
    )


def test_darkpeers_history_rejects_stripped_name_when_expected_group_is_missing() -> None:
    history = [
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": "Waterworld.1995",
            "data": {"importedPath": CURRENT_PATH},
        }
    ]

    assert (
        DarkPeers._history_source_title(
            history,
            CURRENT_PATH,
            allow_latest_import_fallback=False,
            expected_group="VECTOR",
        )
        is None
    )


def test_darkpeers_generic_history_never_uses_unrelated_latest_import() -> None:
    history = {
        "records": [
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Jurassic.Park.3.2001.2160p.UHD.BluRay-VECTOR",
                "data": {"importedPath": "/data/media/movies/Jurassic Park III (2001)/Jurassic.Park.3.2001.mkv"},
            }
        ]
    }

    assert (
        DarkPeers._history_source_title(
            history,
            CURRENT_PATH,
            allow_latest_import_fallback=False,
        )
        is None
    )


def test_darkpeers_movie_scoped_history_can_follow_a_radarr_rename() -> None:
    history = [
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": ORIGINAL,
            "data": {"importedPath": "/data/media/movies/Waterworld (1995) [tmdb-9804]/old-name.mkv"},
        }
    ]

    assert (
        DarkPeers._history_source_title(
            history,
            CURRENT_PATH,
            allow_latest_import_fallback=True,
            expected_group="VECTOR",
        )
        == ORIGINAL
    )
