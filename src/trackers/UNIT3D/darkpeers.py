# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
"""DarkPeers safety overrides for original-release-name enforcement.

DarkPeers rule 4.12 forbids re-tags. The main adapter historically generated a
new Movie/TV name when a release was not detected as scene. For Radarr-backed
movies that have since been renamed, recover the original imported sourceTitle
and submit it byte-for-byte instead of rebuilding the release name.
"""

import os
from collections.abc import Mapping
from typing import Any, cast

import httpx

from src.console import logger
from src.meta import Meta
from src.trackers.UNIT3D.darkpeers_base import DarkPeers as _DarkPeersBase


class DarkPeers(_DarkPeersBase):
    """DarkPeers adapter with fail-safe original naming for Radarr movies."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._original_movie_name_cache: dict[str, str] = {}

    @staticmethod
    def _normalize_path(value: object) -> str:
        text = str(value or "").strip()
        return os.path.normpath(text).casefold() if text else ""

    @staticmethod
    def _source_title_matches_group(source_title: str, expected_group: str | None) -> bool:
        """Check whether a Radarr sourceTitle carries the expected release group."""
        group = str(expected_group or "").lstrip("-").strip().casefold()
        if not group:
            return True

        # sourceTitle normally has no extension. Do not use os.path.splitext()
        # here because dots are part of release names (for example
        # ``...HDR.x265-VECTOR``) and splitext would incorrectly treat
        # ``.x265-VECTOR`` as a file extension, removing the release group.
        title = str(source_title or "").strip().casefold()
        for extension in (".mkv", ".mp4", ".m2ts", ".avi", ".ts", ".mov", ".wmv"):
            if title.endswith(extension):
                title = title[: -len(extension)]
                break

        return title.endswith(f"-{group}") or title.startswith(f"{group}-")

    @classmethod
    def _history_source_title(
        cls,
        records: object,
        current_path: str | None = None,
        *,
        allow_latest_import_fallback: bool = True,
        expected_group: str | None = None,
    ) -> str | None:
        """Return a trustworthy Radarr import sourceTitle.

        Exact imported-path matches are preferred. When Upload-Assistant adds a
        newly-created torrent back to qBittorrent, Radarr can later record a
        newer, stripped sourceTitle such as ``Waterworld.1995`` for the same
        imported path. If a release group is known, only history entries carrying
        that group are eligible so the stripped entry cannot shadow the original
        release name required by DarkPeers rule 4.12.

        Falling back to the newest import is permitted only for Radarr's
        movie-scoped history endpoint; some Radarr versions ignore movieId on the
        generic history endpoint.
        """
        raw_records: object
        if isinstance(records, Mapping):
            raw_records = records.get("records", [])
        else:
            raw_records = records
        if not isinstance(raw_records, list):
            return None

        current_norm = cls._normalize_path(current_path)
        exact_titles: list[str] = []
        import_titles: list[str] = []

        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                continue
            record = cast(Mapping[str, Any], raw_record)
            if str(record.get("eventType") or "").casefold() != "downloadfolderimported":
                continue

            source_title = str(record.get("sourceTitle") or "").strip()
            if not source_title:
                continue
            import_titles.append(source_title)

            data = record.get("data", {})
            if isinstance(data, Mapping) and current_norm:
                imported_path = cls._normalize_path(data.get("importedPath"))
                if imported_path and imported_path == current_norm:
                    exact_titles.append(source_title)

        def eligible(titles: list[str]) -> str | None:
            for title in titles:
                if cls._source_title_matches_group(title, expected_group):
                    return title
            return None

        if exact_titles:
            return eligible(exact_titles)
        if allow_latest_import_fallback and import_titles:
            return eligible(import_titles)
        return None

    def _radarr_enabled(self, meta: Meta) -> bool:
        default = self.config.get("DEFAULT", {})
        return bool(
            isinstance(default, dict)
            and default.get("use_radarr", False)
            and meta.tmdb_id
            and any(str(key).startswith("radarr_api_key") for key in default)
        )

    async def _resolve_original_movie_name(self, meta: Meta) -> str:
        """Resolve the exact release name used by Radarr when this movie imported."""
        scene_name = str(meta.scene_name or "").strip()
        if scene_name:
            return scene_name
        if str(meta.category or "").upper() != "MOVIE" or not self._radarr_enabled(meta):
            return ""

        try:
            tmdb_id = int(meta.tmdb_id or 0)
        except (TypeError, ValueError):
            return ""
        if tmdb_id <= 0:
            return ""

        expected_group = str(meta.tag or "").lstrip("-").strip()
        cache_key = f"{tmdb_id}:{expected_group.casefold()}"
        cached = self._original_movie_name_cache.get(cache_key)
        if cached:
            return cached

        default_raw = self.config.get("DEFAULT", {})
        default = cast(dict[str, Any], default_raw) if isinstance(default_raw, dict) else {}

        async with httpx.AsyncClient() as client:
            for instance_index in range(4):
                suffix = "" if instance_index == 0 else f"_{instance_index}"
                api_key = str(default.get(f"radarr_api_key{suffix}") or "").strip()
                base_url = str(default.get(f"radarr_url{suffix}") or "").strip().rstrip("/")
                if not api_key or not base_url:
                    continue

                headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
                try:
                    movie_response = await client.get(
                        f"{base_url}/api/v3/movie?tmdbId={tmdb_id}&excludeLocalCovers=true",
                        headers=headers,
                        timeout=10.0,
                    )
                except (httpx.TimeoutException, httpx.RequestError):
                    continue
                if movie_response.status_code != 200:
                    continue

                try:
                    movie_payload = movie_response.json()
                except (ValueError, TypeError):
                    continue
                if not isinstance(movie_payload, list) or not movie_payload or not isinstance(movie_payload[0], Mapping):
                    continue

                movie = cast(Mapping[str, Any], movie_payload[0])
                movie_id = movie.get("id")
                movie_file = movie.get("movieFile", {})
                current_path = str(movie_file.get("path") or "") if isinstance(movie_file, Mapping) else ""
                if not isinstance(movie_id, int) or movie_id <= 0:
                    continue

                endpoints = (
                    (f"{base_url}/api/v3/history/movie?movieId={movie_id}", True),
                    (
                        f"{base_url}/api/v3/history?movieId={movie_id}&page=1&pageSize=100&sortKey=date&sortDirection=descending&includeMovie=false",
                        False,
                    ),
                )
                for url, allow_latest in endpoints:
                    try:
                        history_response = await client.get(url, headers=headers, timeout=10.0)
                    except (httpx.TimeoutException, httpx.RequestError):
                        continue
                    if history_response.status_code != 200:
                        continue
                    try:
                        history = history_response.json()
                    except (ValueError, TypeError):
                        continue

                    source_title = self._history_source_title(
                        history,
                        current_path,
                        allow_latest_import_fallback=allow_latest,
                        expected_group=expected_group or None,
                    )
                    if source_title:
                        self._original_movie_name_cache[cache_key] = source_title
                        logger.info(f"{self.tracker}: using original Radarr release name '{source_title}'")
                        return source_title

        return ""

    async def get_additional_checks(self, meta: Meta) -> bool:
        # Rule 4.12 is explicitly bannable. If Radarr integration is enabled for
        # a non-scene movie, never fall back to a generated re-tag when import
        # provenance cannot be recovered.
        if str(meta.category or "").upper() == "MOVIE" and not str(meta.scene_name or "").strip() and self._radarr_enabled(meta):
            if not await self._resolve_original_movie_name(meta):
                logger.info(
                    f"{self.tracker}: [bold red]could not recover the original Radarr release name required by rule 4.12. Skipping upload to avoid a re-tag.[/bold red]"
                )
                return False
        return await super().get_additional_checks(meta)

    async def get_name(self, meta: Meta) -> dict[str, str]:
        if str(meta.category or "").upper() == "MOVIE":
            original_name = await self._resolve_original_movie_name(meta)
            if original_name:
                # Do not apply Dual-Audio/MULTi substitutions or any other
                # tracker naming cleanup: DarkPeers requires the exact original.
                return {"name": original_name}
        return await super().get_name(meta)
