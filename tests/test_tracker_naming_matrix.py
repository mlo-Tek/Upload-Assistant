"""Tracker-specific naming regression matrix for DarkPeers and Luminarr."""

import asyncio

import pytest

from src.meta import Meta
from src.trackers.UNIT3D.darkpeers import DarkPeers
from src.trackers.UNIT3D.luminarr import Luminarr


def _darkpeers(meta: Meta) -> DarkPeers:
    return DarkPeers({"DEFAULT": {"tmdb_api": "test-key"}, "TRACKERS": {"DARKPEERS": {}}})


def _luminarr() -> Luminarr:
    return Luminarr({"DEFAULT": {"tmdb_api": "test-key"}, "TRACKERS": {"LUMINARR": {}}})


@pytest.mark.parametrize(
    ("original", "tracks", "expected"),
    [
        ("English", ["English"], "SKIPPED"),
        ("English", ["English", "German"], "German MULTi"),
        ("English", ["English", "German", "French"], "MULTi"),
        ("Japanese", ["English"], "Dubbed"),
        ("Japanese", ["Japanese", "English"], "Dual-Audio"),
        ("Japanese", ["Japanese", "German"], "German MULTi"),
        ("Japanese", ["Japanese", "English", "German"], "MULTi"),
        ("Japanese", ["English", "German"], "German MULTi"),
        ("Japanese", ["Swedish"], "Swedish Dubbed"),
    ],
)
def test_darkpeers_dub_decision_matrix(original: str, tracks: list[str], expected: str) -> None:
    meta = Meta(category="MOVIE", original_language=original, audio_languages=tracks, language_checked=True)
    assert _darkpeers(meta)._darkpeers_audio_tag(meta) == expected


def test_darkpeers_waterworld_tracker_title() -> None:
    adapter = _darkpeers(Meta())
    meta = Meta(
        category="MOVIE",
        name="Waterworld 1995 2160p UHD BluRay Dual-Audio DTSX 7.1 DV HDR x265-VECTOR",
        original_language="English",
        audio_languages=["German", "English"],
        language_checked=True,
        audio="DTSX 7.1",
        channels="7.1",
    )
    assert asyncio.run(adapter.get_name(meta))["name"] == "Waterworld 1995 2160p UHD BluRay German MULTi DTS:X 7.1 DV HDR x265-VECTOR"


@pytest.mark.parametrize(
    ("original", "tracks", "expected"),
    [
        ("English", ["English"], ""),
        ("English", ["English", "German"], "German Multi"),
        ("en-US", ["en", "de-DE"], "German Multi"),
        ("English", ["English", "German", "French"], "Multi"),
        ("Japanese", ["Japanese", "English"], "Dual-Audio"),
        ("Japanese", ["English"], "Dubbed"),
        ("Japanese", ["Japanese", "German"], "German Multi"),
        ("Japanese", ["Japanese", "English", "German"], "Multi"),
    ],
)
def test_luminarr_dub_decision_matrix(original: str, tracks: list[str], expected: str) -> None:
    meta = Meta(category="MOVIE", original_language=original, audio_languages=tracks)
    assert _luminarr()._luminarr_dub_label(meta) == expected


def test_luminarr_replaces_generic_dual_audio_for_english_original() -> None:
    meta = Meta(
        category="MOVIE",
        name="Waterworld 1995 2160p UHD BluRay Dual-Audio DTS:X 7.1 DV HDR x265-VECTOR",
        original_language="English",
        audio_languages=["English", "German"],
    )
    assert asyncio.run(_luminarr().get_name(meta))["name"] == "Waterworld 1995 2160p UHD BluRay German Multi DTS:X 7.1 DV HDR x265-VECTOR"


def test_luminarr_inserts_missing_language_element_before_audio() -> None:
    meta = Meta(
        category="MOVIE",
        name="Movie 2026 1080p BluRay DTS 5.1 x265-GROUP",
        original_language="English",
        audio_languages=["English", "German"],
        audio="DTS 5.1",
    )
    assert asyncio.run(_luminarr().get_name(meta))["name"] == "Movie 2026 1080p BluRay German Multi DTS 5.1 x265-GROUP"


def test_luminarr_deduplicates_language_variants() -> None:
    meta = Meta(original_language="English", audio_languages=["English", "en-US", "German", "de-DE"])
    assert _luminarr()._luminarr_dub_label(meta) == "German Multi"
