import pytest

from src.meta import Meta
from src.torrent_policy import GIB, LDU_POLICY, MIB, TorrentStats, ldu_piece_size
from src.trackers.UNIT3D.lastdigitalunderground import LastDigitalUnderground


def make_meta(**kwargs) -> Meta:
    values = {
        "category": "MOVIE",
        "name": "Test Movie 2020 2160p BluRay x265",
        "original_language": "en",
        "audio": "DD+ 5.1",
        "audio_languages": ["English"],
        "subtitle_languages": [],
        "edition": "",
        "keywords": [],
        "combined_genres": "Drama",
        "imdb_info": {"runtime": 120, "sound_mixes": []},
        "mal_id": 0,
    }
    values.update(kwargs)
    meta = Meta()
    for key, value in values.items():
        setattr(meta, key, value)
    return meta


def make_tracker() -> LastDigitalUnderground:
    return LastDigitalUnderground({"TRACKERS": {"LASTDIGITALUNDERGROUND": {"api_key": "fake_key"}}})


@pytest.mark.asyncio
async def test_english_film_with_german_dual_audio_gets_no_language_tags():
    meta = make_meta(audio_languages=["German", "English"], subtitle_languages=["German", "English"])
    assert (await make_tracker().get_name(meta))["name"] == "Test Movie 2020 2160p BluRay x265"


@pytest.mark.asyncio
async def test_german_original_lists_original_language_not_first_track():
    meta = make_meta(original_language="de", audio_languages=["English", "German"], subtitle_languages=["English"])
    assert (await make_tracker().get_name(meta))["name"].endswith(" [DEU] [Subs ENG]")


@pytest.mark.asyncio
async def test_non_english_subtitles_are_not_listed():
    meta = make_meta(original_language="de", audio_languages=["German"], subtitle_languages=["German"])
    assert (await make_tracker().get_name(meta))["name"].endswith(" [DEU]")


@pytest.mark.asyncio
async def test_dubbed_only_release_of_english_film_is_tagged_with_its_audio_language():
    meta = make_meta(audio_languages=["German"], subtitle_languages=["English"])
    assert (await make_tracker().get_name(meta))["name"].endswith(" [DEU] [Subs ENG]")


@pytest.mark.asyncio
async def test_no_subs_flag_is_listed():
    meta = make_meta(original_language="fr", audio_languages=["French"], no_subs=True)
    assert (await make_tracker().get_name(meta))["name"].endswith(" [FRA] [NoSubs]")


@pytest.mark.asyncio
async def test_silent_film_lists_only_english_subs():
    meta = make_meta(silent=True, original_language="de", audio_languages=[], subtitle_languages=["German", "English"])
    assert (await make_tracker().get_name(meta))["name"].endswith(" [Subs ENG]")


@pytest.mark.asyncio
async def test_holiday_ranks_before_musical():
    meta = make_meta(combined_genres="Musical, Family, Christmas")
    assert (await make_tracker().get_category_id(meta))["category_id"] == "24"
    meta = make_meta(combined_genres="Musical")
    assert (await make_tracker().get_category_id(meta))["category_id"] == "25"


@pytest.mark.asyncio
async def test_non_english_film_without_subs_goes_to_nosub_nodub():
    meta = make_meta(original_language="de", audio_languages=["German"], subtitle_languages=["German"])
    assert (await make_tracker().get_category_id(meta))["category_id"] == "22"


@pytest.mark.parametrize(
    "size, expected",
    [
        (1 * GIB, 1 * MIB),
        (2 * GIB - 1, 1 * MIB),
        (2 * GIB, 2 * MIB),
        (4 * GIB, 4 * MIB),
        (8 * GIB, 8 * MIB),
        (16 * GIB - 1, 8 * MIB),
        (16 * GIB, 16 * MIB),
        (60 * GIB, 16 * MIB),
        (150 * GIB, 16 * MIB),
    ],
)
def test_ldu_piece_size_follows_rule_10(size, expected):
    assert ldu_piece_size(size) == expected
    assert LDU_POLICY.choose_piece_size(size, 128 * MIB) == expected


def test_ldu_policy_rejects_other_piece_sizes():
    size = 60 * GIB
    ok = TorrentStats(piece_size=16 * MIB, piece_count=size // (16 * MIB), content_size=size, metainfo_size=1)
    too_big = TorrentStats(piece_size=32 * MIB, piece_count=size // (32 * MIB), content_size=size, metainfo_size=1)
    assert LDU_POLICY.accepts(ok)
    assert not LDU_POLICY.accepts(too_big)
    assert LastDigitalUnderground.torrent_policy is LDU_POLICY
