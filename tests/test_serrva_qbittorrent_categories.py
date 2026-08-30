import os
from pathlib import Path

import pytest

from src.meta import Meta
from src.torrent_clients.serrva_qbittorrent import SerrvaQbittorrentClientMixin


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/data/media/movies/Film (2026)/Film.mkv", "movies"),
        ("/data/media/movies-kids/Film (2026)/Film.mkv", "movies-kids"),
        ("/data/media/tv/Show (2026)/Season 01/Episode.mkv", "tv"),
        ("/data/media/tv-kids/Show (2026)/Season 01/Episode.mkv", "tv-kids"),
        ("/data/media/other/file.mkv", None),
    ],
)
def test_category_for_media_path(path: str, expected: str | None) -> None:
    assert SerrvaQbittorrentClientMixin.category_for_media_path(path) == expected


@pytest.mark.asyncio
async def test_single_movie_upload_gets_release_folder_with_nfos(tmp_path: Path) -> None:
    source_dir = tmp_path / "media" / "Waterworld (1995)"
    source_dir.mkdir(parents=True)
    video = source_dir / "Waterworld.1995.mkv"
    video.write_bytes(b"video")
    matching_nfo = source_dir / "Waterworld.1995.nfo"
    matching_nfo.write_text("movie metadata", encoding="utf-8")
    conventional_nfo = source_dir / "movie.nfo"
    conventional_nfo.write_text("more metadata", encoding="utf-8")

    upload_root = tmp_path / "torrents" / "uploads"
    upload_root.mkdir(parents=True)
    mixin = SerrvaQbittorrentClientMixin()
    mixin.config = {"TRACKERS": {"LUMINARR": {"link_dir_name": "luminarr"}}}
    meta = Meta({"category": "MOVIE", "path": str(source_dir), "filelist": [str(video)]})
    client = {"linking": "hardlink", "linked_folder": [str(upload_root)]}

    linked_media = await mixin._prepare_single_file_upload_folder(meta, "LUMINARR", client, video)

    release_dir = upload_root / "luminarr" / "Waterworld.1995"
    assert linked_media == str(release_dir / video.name)
    assert os.path.samefile(video, release_dir / video.name)
    assert os.path.samefile(matching_nfo, release_dir / matching_nfo.name)
    assert os.path.samefile(conventional_nfo, release_dir / conventional_nfo.name)


@pytest.mark.asyncio
async def test_single_tv_upload_only_links_matching_episode_nfo(tmp_path: Path) -> None:
    source_dir = tmp_path / "media" / "Show" / "Season 01"
    source_dir.mkdir(parents=True)
    video = source_dir / "Show.S01E01.mkv"
    video.write_bytes(b"episode")
    matching_nfo = source_dir / "Show.S01E01.nfo"
    matching_nfo.write_text("episode 1", encoding="utf-8")
    unrelated_nfo = source_dir / "Show.S01E02.nfo"
    unrelated_nfo.write_text("episode 2", encoding="utf-8")

    upload_root = tmp_path / "torrents" / "uploads"
    upload_root.mkdir(parents=True)
    mixin = SerrvaQbittorrentClientMixin()
    mixin.config = {"TRACKERS": {"DARKPEERS": {"link_dir_name": "darkpeers"}}}
    meta = Meta({"category": "TV", "path": str(source_dir), "filelist": [str(video)]})
    client = {"linking": "hardlink", "linked_folder": [str(upload_root)]}

    linked_media = await mixin._prepare_single_file_upload_folder(meta, "DARKPEERS", client, video)

    release_dir = upload_root / "darkpeers" / "Show.S01E01"
    assert linked_media == str(release_dir / video.name)
    assert os.path.samefile(video, release_dir / video.name)
    assert os.path.samefile(matching_nfo, release_dir / matching_nfo.name)
    assert not (release_dir / unrelated_nfo.name).exists()
