from typing import Any

from torf import Torrent

from src.console import logger
from src.meta import Meta
from src.torrent_clients.path_utils import is_path_under
from src.torrent_clients.qbittorrent import QbittorrentClientMixin as UpstreamQbittorrentClientMixin


class SerrvaQbittorrentClientMixin(UpstreamQbittorrentClientMixin):
    """Local qBittorrent extensions kept separate from upstream client code."""

    CATEGORY_BY_MEDIA_PATH: tuple[tuple[str, str], ...] = (
        ("/data/media/movies-kids", "movies-kids"),
        ("/data/media/tv-kids", "tv-kids"),
        ("/data/media/movies", "movies"),
        ("/data/media/tv", "tv"),
    )

    @classmethod
    def category_for_media_path(cls, path: str) -> str | None:
        for media_path, category in cls.CATEGORY_BY_MEDIA_PATH:
            if is_path_under(path, media_path):
                return category
        return None

    async def qbittorrent(
        self,
        path: str,
        torrent: Torrent,
        local_path: str,
        remote_path: str,
        client: dict[str, Any],
        _is_disc: str,
        filelist: list[str],
        meta: Meta,
        tracker: str,
        cross: bool = False,
    ) -> None:
        # Preserve upstream precedence:
        #   cross-seed category > explicit --qbit-cat > automatic path mapping
        #   > static qbit_cat from the client config.
        if not cross and not meta.qbit_cat:
            source_path = str(meta.path or path)
            category = self.category_for_media_path(source_path)
            if category:
                meta.qbit_cat = category
                logger.info(f"[cyan]qBittorrent category from media path: {source_path} -> {category}[/cyan]")

        await super().qbittorrent(
            path,
            torrent,
            local_path,
            remote_path,
            client,
            _is_disc,
            filelist,
            meta,
            tracker,
            cross,
        )
