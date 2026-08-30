import os
from pathlib import Path
from typing import Any

from torf import Torrent

from src.console import logger
from src.meta import Meta
from src.torrent_clients.path_utils import coerce_str_list, is_path_under, tracker_directory
from src.torrent_clients.qbittorrent import QbittorrentClientMixin as UpstreamQbittorrentClientMixin
from src.torrent_clients.qbittorrent import async_link_directory


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

    @staticmethod
    def _existing_ancestor(path: Path) -> Path | None:
        """Return the nearest existing path, used for filesystem matching."""
        candidate = path
        while not candidate.exists():
            parent = candidate.parent
            if parent == candidate:
                return None
            candidate = parent
        return candidate

    @classmethod
    def _select_link_target(cls, src: Path, linked_folders: list[str], use_hardlink: bool) -> str | None:
        """Choose a configured link root that can host the source links."""
        if not linked_folders:
            return None
        if not use_hardlink:
            return linked_folders[0]

        try:
            source_device = src.stat().st_dev
        except OSError:
            return linked_folders[0]

        for folder in linked_folders:
            existing = cls._existing_ancestor(Path(folder))
            if existing is None:
                continue
            try:
                if existing.stat().st_dev == source_device:
                    return folder
            except OSError:
                continue
        return None

    @staticmethod
    def _nfo_sidecars(meta: Meta, src: Path) -> list[Path]:
        """Return NFOs that belong beside a single uploaded media file."""
        try:
            nfos = sorted(path for path in src.parent.iterdir() if path.is_file() and path.suffix.casefold() == ".nfo")
        except OSError:
            return []

        # A movie directory normally represents one title, so preserve all NFO
        # sidecars in it (including conventional names such as movie.nfo).
        if str(meta.category or "").upper() == "MOVIE":
            return nfos

        # A TV season directory can contain many episodes. For a single-episode
        # upload, only copy the NFO with the same basename so unrelated episode
        # metadata does not leak into the release folder.
        source_stem = src.stem.casefold()
        return [path for path in nfos if path.stem.casefold() == source_stem]

    async def _prepare_single_file_upload_folder(
        self,
        meta: Meta,
        tracker: str,
        client: dict[str, Any],
        src: Path,
    ) -> str | None:
        """Hard/symlink one Movie/TV file and its NFOs into a release folder.

        Returns the linked media path. Its parent is deliberately passed to
        qBittorrent as the save path by the upstream client implementation.
        """
        linking_method = str(client.get("linking") or "").casefold()
        if linking_method not in {"hardlink", "symlink"}:
            return None

        use_hardlink = linking_method == "hardlink"
        linked_folders = coerce_str_list(client.get("linked_folder", []))
        link_target = self._select_link_target(src, linked_folders, use_hardlink)
        if not link_target:
            logger.info(f"[bold red]No suitable linked folder found for single-file upload: {src}")
            return None

        tracker_cfg = self.config.get("TRACKERS", {}).get(tracker.upper(), {})
        link_dir_name = str(tracker_cfg.get("link_dir_name", "")).strip() if isinstance(tracker_cfg, dict) else ""
        try:
            tracker_dir = tracker_directory(link_target, link_dir_name, tracker)
        except ValueError as exc:
            logger.info(f"[bold red]Invalid tracker link directory for {tracker}: {exc}")
            return None

        release_dir = Path(tracker_dir) / src.stem
        linked_media = release_dir / src.name
        if not await async_link_directory(str(src), str(linked_media), use_hardlink=use_hardlink):
            return None

        for nfo in self._nfo_sidecars(meta, src):
            linked_nfo = release_dir / nfo.name
            if not await async_link_directory(str(nfo), str(linked_nfo), use_hardlink=use_hardlink):
                logger.info(f"[bold red]Failed to link NFO sidecar: {nfo}")
                return None

        logger.info(f"[cyan]Prepared release upload folder: {release_dir}[/cyan]")
        return str(linked_media)

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

        # Upstream places single-file torrents directly in the tracker link
        # directory. For Movie/TV uploads, prepare an extra per-release folder
        # first so media and NFO sidecars stay together:
        #   .../uploads/<tracker>/<release>/<release>.mkv
        #   .../uploads/<tracker>/<release>/<release>.nfo
        # Multi-file/season uploads already retain their source directory tree,
        # so they continue through the upstream path unchanged.
        if not cross and str(meta.category or "").upper() in {"MOVIE", "TV"}:
            meta_filelist = meta.filelist if isinstance(meta.filelist, list) else []
            if len(meta_filelist) == 1:
                source_file = Path(str(meta_filelist[0]))
                if source_file.is_file():
                    linked_media = await self._prepare_single_file_upload_folder(meta, tracker, client, source_file)
                    if linked_media:
                        # The links are already prepared. Disable upstream linking
                        # for this call only and hand it the linked media path. The
                        # upstream single-file path normalization then uses the
                        # release directory as qBittorrent's save path. Also keep
                        # automatic management disabled, matching normal linking.
                        prepared_client = dict(client)
                        prepared_client["linking"] = None
                        prepared_client["automatic_management_paths"] = ""
                        await super().qbittorrent(
                            linked_media,
                            torrent,
                            local_path,
                            remote_path,
                            prepared_client,
                            _is_disc,
                            filelist,
                            meta,
                            tracker,
                            cross,
                        )
                        return

                    if not client.get("allow_fallback", True):
                        logger.info("[bold red]Release-folder linking failed and fallback is disabled; aborting qBittorrent add")
                        return
                    logger.info("[yellow]Release-folder linking failed; falling back to the standard qBittorrent linking path[/yellow]")

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
