import pytest

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
